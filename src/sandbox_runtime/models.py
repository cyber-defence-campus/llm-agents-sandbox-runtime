from typing import Any, List
from pydantic import BaseModel


class SandboxRequest(BaseModel):
    session_id: str
    networks: List[str] | None = None
    # Allow the operator to move within the declared lab CIDR while denying
    # egress over the platform network used to control the sandbox.
    egress_cidr: str | None = None
    # Optional per-run network boundary. The operator may reach the granted
    # entry address for RCE and beacon installation, but not lateral hosts on
    # the same Docker segment. The restriction is installed before the tool
    # server starts and its network-admin capability is then dropped.
    restricted_cidr: str | None = None
    allowed_address: str | None = None


class SandboxInfo(BaseModel):
    session_id: str
    container_id: str
    tool_server_port: int
    tool_server_token: str
    api_url: str


class SandboxListResponse(BaseModel):
    sandboxes: List[SandboxInfo]


class ToolExecutionRequest(BaseModel):
    session_id: str
    agent_id: str
    tool_name: str
    kwargs: dict[str, Any]
    correlation_id: str | None = None


class FileInjectionRequest(BaseModel):
    src_path: str
    dest_path: str
