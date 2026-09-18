import asyncio
import logging
import secrets
import socket
import time
import os
import tarfile
from typing import Any, Dict, Optional, Tuple

import docker
from docker.errors import DockerException, NotFound, APIError
from docker.models.containers import Container
import httpx

from .config import (
    AGENT_NETWORK_MODE,
    AGENT_NETWORK_NAME,
    AGENT_SANDBOX_IMAGE,
    AGENT_SANDBOX_VOLUMES,
)

logger = logging.getLogger("sandbox_service.manager")

# A tool server that is slow is not a dead sandbox. The health check used a
# 2 s request and three consecutive misses tore the container down, which on
# a busy host destroyed a live session's terminal mid-run (relay-wazuh,
# seed 0, 2026-09-17). Give the socket five seconds, give a newly created or
# restarted sandbox a grace window, and prefer a restart -- the filesystem
# survives one -- before taking the container away.
HEALTH_TIMEOUT = 5.0
HEALTH_GRACE = 15.0
HEALTH_STRIKES = 5
HEALTH_REVIVALS = 2

# A driver that is killed never reaches `release_sandbox`, and the container it
# stood up stays running with nobody talking to it: six were still up twenty
# hours after the interrupted runs of 2026-09-17, on the docker pool every lab
# draws its addresses from. The health loop reaps any sandbox that has taken
# no tool execution for this long -- longer than the longest campaign's own
# timeout, so a live run cannot reach it.
IDLE_REAP_SECONDS = float(os.getenv("SANDBOX_IDLE_REAP_SECONDS", "7200"))


class SandboxManager:
    """
    Manages the lifecycle of Docker containers for sandboxed agent execution.
    Handles creation, health checking, file injection, and destruction.
    """

    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._sandboxes: Dict[str, Dict[str, Any]] = {}
        self.docker = None

        try:
            self.docker = docker.from_env()
            self.docker.ping()
            logger.info("Docker connection established.")
        except DockerException as e:
            logger.critical(f"Failed to connect to Docker: {e}")

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def get_or_create_container(
        self, session_id: str, networks: Optional[list] = None,
        egress_cidr: Optional[str] = None,
        restricted_cidr: Optional[str] = None,
        allowed_address: Optional[str] = None,
    ) -> Container:
        """Retrieve or create a sandbox, applying its optional network boundary."""
        if not self.docker:
            raise RuntimeError("Docker unavailable")
        if egress_cidr and AGENT_NETWORK_MODE == "host":
            raise ValueError("scoped sandbox egress is unsupported in host network mode")
        if bool(restricted_cidr) != bool(allowed_address):
            raise ValueError(
                "restricted_cidr and allowed_address must be supplied together"
            )

        async with self._get_lock(session_id):
            container = await self._find_existing(session_id)
            if not container:
                if networks or egress_cidr or restricted_cidr or allowed_address:
                    container = await self._create_new(
                        session_id, networks=networks,
                        egress_cidr=egress_cidr,
                        restricted_cidr=restricted_cidr,
                        allowed_address=allowed_address)
                else:
                    container = await self._create_new(session_id)

            await self._ensure_networks(container, networks)
            return container

    async def _find_existing(self, session_id: str) -> Optional[Container]:
        name = f"platform-{session_id}"
        try:
            container = await asyncio.to_thread(self.docker.containers.get, name)

            if container.status != "running":
                logger.info(f"Restarting container {name}")
                await asyncio.to_thread(container.start)

            await asyncio.to_thread(container.reload)
            info = self._extract_container_info(container)
            if not info:
                logger.warning(f"Container {name} has missing config. Recreating.")
                await self._remove_container(container)
                return None

            ip, port, token = info
            if await self._healthy_after(ip, port, token, HEALTH_GRACE):
                self._register_sandbox(session_id, container, ip, port, token)
                return container

            if await self._restart_sandbox(session_id):
                return await asyncio.to_thread(
                    self.docker.containers.get, name)

            logger.warning(f"Container {name} unhealthy. Recreating.")
            await self._remove_container(container)
            return None

        except NotFound:
            return None
        except Exception as e:
            logger.error(f"Error checking existing container {name}: {e}")
            return None

    async def _create_new(
        self, session_id: str, networks: Optional[list] = None,
        egress_cidr: Optional[str] = None,
        restricted_cidr: Optional[str] = None,
        allowed_address: Optional[str] = None,
    ) -> Container:
        name = f"platform-{session_id}"
        logger.info(f"Creating new sandbox: {name}")

        try:
            old = await asyncio.to_thread(self.docker.containers.get, name)
            await self._remove_container(old)
        except NotFound:
            pass

        caido_port = self._find_free_port()
        srv_port = self._find_free_port()
        token = secrets.token_urlsafe(32)

        env = {
            "PYTHONUNBUFFERED": "1",
            "CAIDO_PORT": str(caido_port),
            "TOOL_SERVER_PORT": str(srv_port),
            "TOOL_SERVER_TOKEN": token,
            "PYTHONPATH": "/app",
            "AGENT_SANDBOX_MODE": "true",
            "REDIS_HOST": os.getenv("REDIS_HOST", "redis"),
            "REDIS_PORT": os.getenv("REDIS_PORT", "6379"),
            "PLATFORM_SESSION_ID": session_id,
        }
        if restricted_cidr and allowed_address:
            env.update({
                "AGENT_RESTRICTED_CIDR": restricted_cidr,
                "AGENT_ALLOWED_ADDRESS": allowed_address,
                "AGENT_DROP_NET_ADMIN": "1",
            })
        if egress_cidr:
            env.update({
                "AGENT_EGRESS_CIDR": egress_cidr,
                "AGENT_CONTROL_HOST": os.getenv(
                    "AGENT_SANDBOX_SERVICE_HOST", "sandbox-service"
                ),
                "AGENT_DROP_NET_ADMIN": "1",
            })

        labels = {"platform-session-id": session_id}
        volumes = self._parse_volumes()

        kwargs = {
            "detach": True,
            "name": name,
            "image": AGENT_SANDBOX_IMAGE,
            "environment": env,
            "labels": labels,
            "volumes": volumes,
            "cap_add": ["NET_ADMIN", "NET_RAW"],
            "tty": True,
        }

        if AGENT_NETWORK_MODE == "host":
            kwargs["network_mode"] = "host"
        else:
            kwargs["network"] = AGENT_NETWORK_NAME

        for attempt in range(3):
            try:
                # Attach the lab segment before the entrypoint runs. The
                # entrypoint installs the allow-one-host route while it still
                # has NET_ADMIN, then drops that capability before starting
                # the tool server and its persistent terminal shell.
                if networks and AGENT_NETWORK_MODE != "host":
                    container = await asyncio.to_thread(
                        self.docker.containers.create, **kwargs)
                    for network_name in networks:
                        network = await asyncio.to_thread(
                            self.docker.networks.get, network_name)
                        await asyncio.to_thread(network.connect, container)
                    await asyncio.to_thread(container.start)
                else:
                    container = await asyncio.to_thread(
                        self.docker.containers.run, **kwargs)

                await asyncio.to_thread(container.reload)
                ip = self._get_ip(container)

                await self._wait_for_health(container, ip, srv_port, token)

                self._register_sandbox(session_id, container, ip, srv_port, token)
                return container

            except APIError as e:
                # 409 Conflict: Container removal in progress or name collision
                if e.response.status_code == 409 and attempt < 2:
                    logger.warning(f"Sandbox creation conflict (attempt {attempt+1}/3): {e}")
                    try:
                        c = await asyncio.to_thread(self.docker.containers.get, name)
                        await self._remove_container(c)

                        for _ in range(10):
                            try:
                                await asyncio.to_thread(self.docker.containers.get, name)
                                await asyncio.sleep(0.5)
                            except NotFound:
                                break
                    except (NotFound, APIError):
                        pass
                    
                    await asyncio.sleep(1.0)
                    continue

                logger.error(f"Failed to launch sandbox {session_id}: {e}")
                raise RuntimeError(f"Sandbox creation failed: {e}")

            except Exception as e:
                logger.error(f"Failed to launch sandbox {session_id}: {e}")
                try:
                    c = self.docker.containers.get(name)
                    await self._remove_container(c)
                except:
                    pass
                raise RuntimeError(f"Sandbox creation failed: {e}")

    async def _ensure_networks(
        self, container: Container, networks: Optional[list]
    ) -> None:
        if not networks:
            return

        await asyncio.to_thread(container.reload)
        attached = set(
            (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        )

        for name in networks:
            if name in attached:
                continue
            try:
                network = await asyncio.to_thread(self.docker.networks.get, name)
                await asyncio.to_thread(network.connect, container)
                logger.info(f"Connected {container.name} to network {name}")
            except NotFound:
                logger.error(
                    f"Network {name} not found; {container.name} was not connected to it"
                )
            except APIError as e:
                logger.warning(f"Failed to connect {container.name} to {name}: {e}")

    async def stop_remove_sandbox(self, session_id: str, cancel_task: bool = True):
        entry = self.sandboxes.pop(session_id, None)
        if entry and cancel_task:
            task = entry.get("health_task")
            if task:
                task.cancel()

        name = f"platform-{session_id}"
        try:
            container = await asyncio.to_thread(self.docker.containers.get, name)
            await self._remove_container(container)
            logger.info(f"Removed sandbox {session_id}")
        except NotFound:
            pass
        except Exception as e:
            logger.error(f"Error removing sandbox {session_id}: {e}")

    async def copy_file(self, session_id: str, src: str, dest: str):
        """Injects file into container using disk-based buffering for large files."""
        import tempfile

        c = await self._find_existing(session_id)
        if not c:
            raise RuntimeError("Sandbox not active")

        dest_dir = "/".join(dest.split("/")[:-1])
        if dest_dir:
            await asyncio.to_thread(c.exec_run, f"mkdir -p {dest_dir}")

        try:
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=True) as tmp:
                with tarfile.open(fileobj=tmp, mode="w") as tar:
                    tar.add(src, arcname=dest.split("/")[-1])
                tmp.flush()
                tmp.seek(0)

                await asyncio.to_thread(c.put_archive, dest_dir or "/", tmp)
                logger.info(f"Injected {src} -> {dest} in {session_id}")
        except Exception as e:
            logger.error(f"File copy failed: {e}")
            raise

    def _register_sandbox(
        self, sid: str, container: Container, ip: str, port: int, token: str
    ):
        if sid in self._sandboxes:
            entry = self._sandboxes[sid]
            task = entry.get("health_task")
            if task and not task.done():
                entry["container"] = container
                entry["ip_address"] = ip
                entry["tool_server_port"] = port
                entry["tool_server_token"] = token
                return

        self._sandboxes[sid] = {
            "container": container,
            "ip_address": ip,
            "tool_server_port": port,
            "tool_server_token": token,
            "last_used": time.time(),
            "health_task": asyncio.create_task(self._health_loop(sid, ip, port, token)),
        }

    def note_used(self, session_id: str) -> None:
        """Record that a sandbox just carried out a tool execution.

        This is the only thing that keeps it off the idle list: the reaper
        takes sandboxes a dead driver left behind, and a run that is working
        touches this on every call.
        """
        entry = self._sandboxes.get(session_id)
        if entry is not None:
            entry["last_used"] = time.time()

    async def reap_idle(self, now: float | None = None) -> list[str]:
        """Remove sandboxes no execution has reached for `IDLE_REAP_SECONDS`.

        Returns the session ids removed, so a caller can say what it took.
        """
        moment = time.time() if now is None else now
        reaped: list[str] = []
        for sid, entry in list(self._sandboxes.items()):
            used = float(entry.get("last_used") or moment)
            if moment - used < IDLE_REAP_SECONDS:
                continue
            logger.warning(
                f"Sandbox {sid} took no execution in {moment - used:.0f}s; "
                f"removing it as a leftover.")
            await self.stop_remove_sandbox(sid)
            reaped.append(sid)
        return reaped

    async def _health_loop(self, sid: str, ip: str, port: int, token: str):
        fails = 0
        revivals = 0
        while True:
            await asyncio.sleep(10)
            # A driver killed mid-run leaves its sandbox behind; nothing else
            # in this process ever looks at it again.
            await self.reap_idle()
            if sid not in self._sandboxes:
                break
            if await self._check_health(ip, port, token):
                fails = 0
                continue
            fails += 1
            if fails < HEALTH_STRIKES:
                continue
            if revivals < HEALTH_REVIVALS:
                revivals += 1
                fails = 0
                info = await self._restart_sandbox(sid)
                if info:
                    ip, port, token = info
                    logger.warning(
                        f"Sandbox {sid} restarted after {HEALTH_STRIKES} "
                        f"failed checks.")
                    continue
            logger.error(f"Sandbox {sid} died. Cleaning up.")
            await self.stop_remove_sandbox(sid)
            break

    async def _check_health(self, ip: str, port: int, token: str,
                            timeout: float = HEALTH_TIMEOUT) -> bool:
        if not ip:
            return False
        url = f"http://{ip}:{port}/health"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )
                return (
                    resp.status_code == 200 and resp.json().get("status") == "healthy"
                )
        except Exception:
            return False

    async def _healthy_after(self, ip: str, port: int, token: str,
                            grace: float) -> bool:
        """Whether the tool server answers at any point inside a window."""
        deadline = time.time() + grace
        while True:
            if await self._check_health(ip, port, token):
                return True
            if time.time() >= deadline:
                return False
            await asyncio.sleep(1)

    async def _restart_sandbox(self, sid: str) -> Optional[Tuple[str, int, str]]:
        """Restart a sandbox in place, keeping whatever it has on disk.

        Returns the address it came back on when it is answering again.
        """
        name = f"platform-{sid}"
        try:
            container = await asyncio.to_thread(self.docker.containers.get, name)
            await asyncio.to_thread(container.restart)
            await asyncio.to_thread(container.reload)
            info = self._extract_container_info(container)
            if not info:
                return None
            ip, port, token = info
            self._register_sandbox(sid, container, ip, port, token)
            if await self._healthy_after(ip, port, token, HEALTH_GRACE):
                return info
            return None
        except Exception as error:
            logger.error(f"Could not restart sandbox {name}: {error}")
            return None

    async def _wait_for_health(
        self, container: Container, ip: str, port: int, token: str, timeout: int = 60
    ):
        start = time.time()
        while time.time() - start < timeout:
            if await self._check_health(ip, port, token):
                return
            await asyncio.sleep(1)

            try:
                await asyncio.to_thread(container.reload)
                ip = self._get_ip(container)
            except:
                pass

        raise RuntimeError("Timeout waiting for container health")

    def _extract_container_info(
        self, container: Container
    ) -> Optional[Tuple[str, int, str]]:
        try:
            env_list = container.attrs["Config"]["Env"]
            env = {k: v for k, v in [e.split("=", 1) for e in env_list if "=" in e]}
            port = int(env.get("TOOL_SERVER_PORT", 0))
            token = env.get("TOOL_SERVER_TOKEN", "")
            ip = self._get_ip(container)

            if port and token and ip:
                return ip, port, token
        except Exception:
            pass
        return None

    def _get_ip(self, container: Container) -> str:
        if AGENT_NETWORK_MODE == "host":
            return "host.docker.internal"
        try:
            return container.attrs["NetworkSettings"]["Networks"][AGENT_NETWORK_NAME][
                "IPAddress"
            ]
        except Exception:
            return ""

    def _find_free_port(self) -> int:
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    async def _remove_container(self, container: Container):
        try:
            if container.status == "running":
                await asyncio.to_thread(container.stop, timeout=1)
            await asyncio.to_thread(container.remove, force=True)
        except APIError as e:
            # 409: removal in progress; 404: already gone
            if e.response.status_code in (409, 404):
                pass
            else:
                logger.warning(f"Error removing container: {e}")
        except Exception as e:
            logger.warning(f"Error removing container: {e}")

    def _parse_volumes(self) -> Dict[str, Dict[str, str]]:
        vols = {}
        if not AGENT_SANDBOX_VOLUMES:
            return vols
        for v in AGENT_SANDBOX_VOLUMES.split(","):
            p = v.split(":")
            if len(p) >= 2:
                vols[p[0]] = {"bind": p[1], "mode": p[2] if len(p) > 2 else "rw"}
        return vols

    @property
    def sandboxes(self):
        return self._sandboxes

    stop_and_remove_sandbox = stop_remove_sandbox
    copy_file_to_container = copy_file


sandbox_manager = SandboxManager()
