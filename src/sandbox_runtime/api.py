import asyncio
import logging
import uuid

import httpx
from docker.errors import DockerException, NotFound
from fastapi import FastAPI, HTTPException, status

from .config import AGENT_NETWORK_MODE
from .manager import sandbox_manager
from .models import (
    SandboxInfo,
    SandboxListResponse,
    SandboxRequest,
    ToolExecutionRequest,
    FileInjectionRequest,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox_service")

app = FastAPI(title="Platform Sandbox Service")


@app.get("/sandboxes", response_model=SandboxListResponse)
async def list_sandboxes():
    """List all active sandboxes."""
    active_sandboxes = []
    for session_id, data in sandbox_manager.sandboxes.items():
        container = data.get("container")
        if not container:
            continue

        ip_address = data.get("ip_address", "")
        port = data.get("tool_server_port", 0)
        api_url = f"http://{ip_address}:{port}"

        active_sandboxes.append(
            SandboxInfo(
                session_id=session_id,
                container_id=data.get("container_id", ""),
                tool_server_port=port,
                tool_server_token=data.get("tool_server_token", ""),
                api_url=api_url,
            )
        )
    return SandboxListResponse(sandboxes=active_sandboxes)


@app.post("/sandboxes", response_model=SandboxInfo)
async def create_sandbox(request: SandboxRequest):
    session_id = request.session_id
    try:
        container = await sandbox_manager.get_or_create_container(
            session_id,
            networks=request.networks,
            egress_cidr=request.egress_cidr,
            restricted_cidr=request.restricted_cidr,
            allowed_address=request.allowed_address,
        )
        if session_id not in sandbox_manager.sandboxes:
            logger.critical(
                f"CRITICAL: Sandbox state inconsistency for {session_id} after container creation/retrieval."
            )
            raise HTTPException(
                status_code=500, detail="Sandbox state inconsistency after creation."
            )

        sandbox_data = sandbox_manager.sandboxes[session_id]
        ip_address = sandbox_manager._get_ip(container)
        api_url = f"http://{ip_address}:{sandbox_data['tool_server_port']}"

        return SandboxInfo(
            session_id=session_id,
            container_id=container.id,
            tool_server_port=sandbox_data["tool_server_port"],
            tool_server_token=sandbox_data["tool_server_token"],
            api_url=api_url,
        )
    except HTTPException as e:
        logger.error(
            f"HTTPException during sandbox creation/retrieval for {session_id}: {e.detail}"
        )
        raise e
    except Exception as e:
        logger.exception(f"Error creating/getting sandbox for session_id {session_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sandboxes/{session_id}", status_code=status.HTTP_202_ACCEPTED)
async def destroy_sandbox(session_id: str):
    logger.info(f"Received request to destroy sandbox for session_id: {session_id}")
    await sandbox_manager.stop_and_remove_sandbox(session_id, cancel_task=True)
    return {"session_id": session_id, "message": "Sandbox destruction initiated."}


@app.post("/sandboxes/{session_id}/files", status_code=status.HTTP_201_CREATED)
async def inject_file(session_id: str, request: FileInjectionRequest):
    """INJECTS a file from the host into the sandbox container."""
    logger.info(
        f"Injecting file for session {session_id}: {request.src_path} -> {request.dest_path}"
    )
    try:
        await sandbox_manager.copy_file_to_container(
            session_id, request.src_path, request.dest_path
        )
        return {"message": "File injected successfully."}
    except RuntimeError as e:
        logger.error(f"Failed to inject file for session {session_id}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        logger.error(f"Source file not found for session {session_id}: {e}")
        raise HTTPException(
            status_code=400, detail=f"Source file not found: {request.src_path}"
        )
    except Exception as e:
        logger.exception(
            f"Unexpected error during file injection for session {session_id}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/execute")
async def execute_tool_in_sandbox(request: ToolExecutionRequest):
    session_id = request.session_id
    try:
        await sandbox_manager.get_or_create_container(session_id)
        if session_id not in sandbox_manager.sandboxes:
            raise HTTPException(
                status_code=500,
                detail=f"Sandbox state inconsistency for session_id '{session_id}' after ensuring container exists.",
            )
    except HTTPException as e:
        logger.error(
            f"Failed to ensure sandbox exists for execution request (session={session_id}): {e.detail}"
        )
        raise e
    except Exception as e:
        logger.exception(
            f"Unexpected error ensuring sandbox exists for execution (session={session_id})"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to prepare sandbox for execution: {e}"
        )

    sandbox_info = sandbox_manager.sandboxes[session_id]
    port = sandbox_info["tool_server_port"]
    token = sandbox_info["tool_server_token"]
    container = sandbox_info["container"]
    try:
        await asyncio.get_running_loop().run_in_executor(None, container.reload)
        tool_server_host = sandbox_manager._get_ip(container)
    except Exception:
        tool_server_host = container.name
        if AGENT_NETWORK_MODE == "host":
            tool_server_host = "host.docker.internal"

    tool_server_url = f"http://{tool_server_host}:{port}/execute"

    correlation_id = request.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation_id,
    }

    request_data = {
        "agent_id": request.agent_id,
        "tool_name": request.tool_name,
        "kwargs": request.kwargs,
        "correlation_id": correlation_id,
    }

    logger.info(
        f"Forwarding execution request for '{request.tool_name}' to tool server at {tool_server_url} (CorrID: {correlation_id})"
    )

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                tool_server_url,
                json=request_data,
                headers=headers,
                timeout=None,
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to tool server at {tool_server_url}: {e}")

            container_status = "unknown"
            container_logs = "Could not fetch logs."
            try:
                container.reload()
                container_status = container.status
                logs_bytes = container.logs(tail=100)
                container_logs = logs_bytes.decode("utf-8", errors="ignore")
            except (NotFound, DockerException) as log_err:
                container_status = "removed_or_error"
                container_logs = f"Could not fetch logs: {log_err}"
                sandbox_manager.sandboxes.pop(session_id, None)

            error_detail = (
                f"Could not connect to tool server: {e}. "
                f"Container status: {container_status}.\n\n"
                f"--- Last 100 lines of Sandbox Logs ---\n{container_logs}"
            )

            raise HTTPException(
                status_code=503,
                detail=error_detail,
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Tool server returned an error ({e.response.status_code}): {e.response.text}"
            )
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text
            raise HTTPException(
                status_code=e.response.status_code,
                detail=error_detail,
            )
        except Exception as e:
            logger.exception(f"Unexpected error during tool execution forwarding: {e}")
            raise HTTPException(
                status_code=500, detail=f"Internal error forwarding tool execution: {e}"
            )
