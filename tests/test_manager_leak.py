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


@pytest.mark.asyncio
async def test_an_idle_sandbox_a_dead_driver_left_is_reaped():
    """A killed driver never reaches `release_sandbox`.

    Six sandboxes from the interrupted runs of 2026-09-17 were still up twenty
    hours later, on the docker pool every lab draws its addresses from.
    """
    manager = SandboxManager()
    manager._sandboxes = {
        "orphan": {"last_used": 1000.0},
        "live": {"last_used": 9000.0},
    }
    manager.stop_remove_sandbox = AsyncMock()

    reaped = await manager.reap_idle(now=10000.0)

    assert reaped == ["orphan"]
    manager.stop_remove_sandbox.assert_awaited_once_with("orphan")


@pytest.mark.asyncio
async def test_a_tool_execution_keeps_a_sandbox_off_the_idle_list():
    manager = SandboxManager()
    manager._sandboxes = {"job": {"last_used": 0.0}}

    manager.note_used("job")

    assert manager._sandboxes["job"]["last_used"] > 0.0
