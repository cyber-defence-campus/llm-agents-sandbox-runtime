import logging
import os
import uuid
import httpx
from typing import Any, Dict, Optional

logger = logging.getLogger("sandbox_runtime.client")


class SandboxClient:
    """
    HTTP Client for interacting with the Sandbox Runtime Service.
    Handles sandbox lifecycle (creation, listing, destruction) and tool execution.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv(
            "SANDBOX_RUNTIME_URL", "http://localhost:8000"
        )
        self._timeout = httpx.Timeout(300.0, connect=10.0)

    @property
    def is_available(self) -> bool:
        # Simple check if URL is configured, real check would ping
        return bool(self.base_url)

    async def ensure_sandbox(self, session_id: str) -> Dict[str, Any]:
        """Ensures a sandbox container exists for the given session ID."""
        url = f"{self.base_url}/sandboxes"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                logger.debug(f"Ensuring sandbox presence for session: {session_id}")
                resp = await client.post(url, json={"session_id": session_id})
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to ensure sandbox {session_id}: {e}")
            raise

    async def list_sandboxes(self) -> Dict[str, Any]:
        """Lists active sandboxes managed by the runtime."""
        url = f"{self.base_url}/sandboxes"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to list sandboxes: {e}")
            raise

    async def inject_file(
        self, session_id: str, src_path: str, dest_path: str
    ) -> Dict[str, Any]:
        """
        Injects a file from the host into the sandbox container.
        """
        url = f"{self.base_url}/sandboxes/{session_id}/files"
        payload = {"src_path": src_path, "dest_path": dest_path}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                logger.debug(
                    f"Injecting file into sandbox {session_id}: {src_path} -> {dest_path}"
                )
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to inject file into sandbox {session_id}: {e}")
            raise

    async def execute_tool(
        self,
        session_id: str,
        agent_id: str,
        tool_name: str,
        kwargs: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a tool within the target sandbox.
        """
        if not correlation_id:
            correlation_id = f"corr-{uuid.uuid4().hex[:12]}"

        # Note: API expects 'session_id' in payload
        payload = {
            "session_id": session_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "kwargs": kwargs,
            "correlation_id": correlation_id,
        }

        headers = {"X-Correlation-ID": correlation_id}
        url = f"{self.base_url}/execute"

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                logger.debug(
                    f"Executing '{tool_name}' in sandbox {session_id} (Agent: {agent_id})"
                )
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()

        except httpx.HTTPStatusError as e:
            error_msg = f"Sandbox API Error: {e.response.status_code}"
            try:
                detail = e.response.json()
                error_msg += f" - {detail}"
            except Exception:
                error_msg += f" - {e.response.text}"
            logger.error(error_msg)
            return {"error": error_msg}

        except httpx.RequestError as e:
            logger.exception(f"Connection error to sandbox service: {e}")
            return {"error": f"Sandbox connection failed: {e}"}

    async def destroy_sandbox(self, session_id: str) -> Dict[str, Any]:
        """Terminates the sandbox container."""
        url = f"{self.base_url}/sandboxes/{session_id}"
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                logger.info(f"Destroying sandbox: {session_id}")
                resp = await client.delete(url)
                if resp.status_code >= 400:
                    logger.warning(f"Destroy returned {resp.status_code}: {resp.text}")
                return {"success": resp.status_code < 400}
        except httpx.RequestError as e:
            logger.error(f"Failed to destroy sandbox {session_id}: {e}")
            return {"error": str(e)}


# Global instance
sandbox_client = SandboxClient()
