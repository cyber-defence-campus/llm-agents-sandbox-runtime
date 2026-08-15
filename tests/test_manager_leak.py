import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sandbox_runtime.manager import SandboxManager

@pytest.mark.asyncio
async def test_register_sandbox_idempotency():
    manager = SandboxManager()
    manager._sandboxes = {}

    manager._health_loop = AsyncMock()

    container = MagicMock()

    sid = "test_session"

    manager._register_sandbox(sid, container, "1.2.3.4", 8080, "token")
    assert sid in manager._sandboxes
    assert manager._sandboxes[sid]["ip_address"] == "1.2.3.4"

    task1 = manager._sandboxes[sid]["health_task"]

    manager._register_sandbox(sid, container, "5.6.7.8", 9090, "token2")

    task2 = manager._sandboxes[sid]["health_task"]
    assert task1 is task2

    assert manager._sandboxes[sid]["ip_address"] == "5.6.7.8"
    assert manager._sandboxes[sid]["tool_server_port"] == 9090
