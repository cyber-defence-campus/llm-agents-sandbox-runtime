import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
from sandbox_runtime.manager import SandboxManager

@pytest.mark.asyncio
async def test_register_sandbox_idempotency():
    manager = SandboxManager()
    manager._sandboxes = {}
    
    # Mock health loop to do nothing
    manager._health_loop = AsyncMock()
    
    # Mock container
    container = MagicMock()
    
    sid = "test_session"
    
    # First registration
    manager._register_sandbox(sid, container, "1.2.3.4", 8080, "token")
    assert sid in manager._sandboxes
    assert manager._sandboxes[sid]["ip_address"] == "1.2.3.4"
    
    # Capture the task
    task1 = manager._sandboxes[sid]["health_task"]
    
    # Second registration with same SID but different IP (simulating update)
    manager._register_sandbox(sid, container, "5.6.7.8", 9090, "token2")
    
    # Assert task is the SAME object (no new task created)
    task2 = manager._sandboxes[sid]["health_task"]
    assert task1 is task2
    
    # Assert metadata updated
    assert manager._sandboxes[sid]["ip_address"] == "5.6.7.8"
    assert manager._sandboxes[sid]["tool_server_port"] == 9090
