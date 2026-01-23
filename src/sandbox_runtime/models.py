from typing import Any, List
from pydantic import BaseModel


class SandboxRequest(BaseModel):
    session_id: str


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
