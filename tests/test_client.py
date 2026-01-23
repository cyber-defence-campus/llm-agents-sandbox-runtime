import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock, patch
from sandbox_runtime.client import SandboxClient


@pytest.fixture
def sandbox_client():
    return SandboxClient(base_url="http://test-sandbox")


@pytest.mark.asyncio
async def test_ensure_sandbox(sandbox_client):
    """Test ensuring a sandbox exists."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "session_id": "sess1",
            "api_url": "http://1.2.3.4:1234",
        }
        mock_post.return_value = mock_response

        result = await sandbox_client.ensure_sandbox("sess1")

        assert result["session_id"] == "sess1"
        assert result["api_url"] == "http://1.2.3.4:1234"
        mock_post.assert_called_once()
        assert mock_post.call_args[1]["json"] == {"session_id": "sess1"}


@pytest.mark.asyncio
async def test_ensure_sandbox_error(sandbox_client):
    """Test error when ensuring sandbox."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = httpx.HTTPError("Connection failed")

        with pytest.raises(httpx.HTTPError):
            await sandbox_client.ensure_sandbox("sess1")


@pytest.mark.asyncio
async def test_list_sandboxes(sandbox_client):
    """Test listing sandboxes."""
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"sandboxes": []}
        mock_get.return_value = mock_response

        result = await sandbox_client.list_sandboxes()
        assert result == {"sandboxes": []}


@pytest.mark.asyncio
async def test_execute_tool(sandbox_client):
    """Test tool execution."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "output": "done"}
        mock_post.return_value = mock_response

        result = await sandbox_client.execute_tool(
            session_id="job1",
            agent_id="agent1",
            tool_name="shell",
            kwargs={"cmd": "ls"},
        )

        assert result["status"] == "ok"
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["session_id"] == "job1"
        assert payload["tool_name"] == "shell"


@pytest.mark.asyncio
async def test_execute_tool_error(sandbox_client):
    """Test execution error handling."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"
        mock_post.side_effect = httpx.HTTPStatusError(
            "500 Error", request=MagicMock(), response=mock_response
        )

        result = await sandbox_client.execute_tool("job1", "agent1", "shell", {})

        assert "error" in result
        assert "Sandbox API Error: 500" in result["error"]


@pytest.mark.asyncio
async def test_destroy_sandbox(sandbox_client):
    """Test destroying a sandbox."""
    with patch("httpx.AsyncClient.delete") as mock_delete:
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_delete.return_value = mock_response

        result = await sandbox_client.destroy_sandbox("sess1")
        assert result["success"] is True


@pytest.mark.asyncio
async def test_destroy_sandbox_failure(sandbox_client):
    """Test destroying a sandbox failure."""
    with patch("httpx.AsyncClient.delete") as mock_delete:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_delete.return_value = mock_response

        result = await sandbox_client.destroy_sandbox("sess1")
        assert result["success"] is False
