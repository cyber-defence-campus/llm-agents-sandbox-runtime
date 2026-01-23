import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import status


def test_list_sandboxes(mock_api_client, mock_global_manager, mock_container):
    """Test retrieving list of active sandboxes."""
    mock_global_manager.sandboxes = {
        "sess1": {
            "container": mock_container,
            "ip_address": "1.2.3.4",
            "tool_server_port": 8080,
            "container_id": "cid1",
            "tool_server_token": "tok1",
        }
    }

    response = mock_api_client.get("/sandboxes")

    assert response.status_code == 200
    data = response.json()
    assert len(data["sandboxes"]) == 1
    assert data["sandboxes"][0]["session_id"] == "sess1"


def test_create_sandbox_success(mock_api_client, mock_global_manager, mock_container):
    """Test successful sandbox creation."""
    mock_global_manager.get_or_create_container = AsyncMock(return_value=mock_container)
    mock_global_manager._get_ip.return_value = "1.2.3.4"
    mock_global_manager.sandboxes = {
        "new_sess": {
            "tool_server_port": 1234,
            "tool_server_token": "token",
            "container": mock_container,
        }
    }

    response = mock_api_client.post("/sandboxes", json={"session_id": "new_sess"})

    assert response.status_code == 200
    assert response.json()["session_id"] == "new_sess"


def test_create_sandbox_inconsistency_error(mock_api_client, mock_global_manager):
    """Test error when state is inconsistent after creation."""
    mock_global_manager.get_or_create_container = AsyncMock()
    mock_global_manager.sandboxes = {}  # Missing session

    response = mock_api_client.post("/sandboxes", json={"session_id": "sess"})

    assert response.status_code == 500
    assert "inconsistency" in response.json()["detail"]


def test_destroy_sandbox(mock_api_client, mock_global_manager):
    """Test destroying a sandbox."""
    mock_global_manager.stop_and_remove_sandbox = AsyncMock()

    response = mock_api_client.delete("/sandboxes/sess1")

    assert response.status_code == 202
    mock_global_manager.stop_and_remove_sandbox.assert_called_once_with(
        "sess1", cancel_task=True
    )


def test_inject_file_success(mock_api_client, mock_global_manager):
    """Test successful file injection."""
    mock_global_manager.copy_file_to_container = AsyncMock()

    response = mock_api_client.post(
        "/sandboxes/sess1/files", json={"src_path": "/src", "dest_path": "/dest"}
    )

    assert response.status_code == 201
    mock_global_manager.copy_file_to_container.assert_called_once()


def test_inject_file_errors(mock_api_client, mock_global_manager):
    """Test error cases for file injection."""
    # 404 Case
    mock_global_manager.copy_file_to_container.side_effect = RuntimeError("Not active")
    resp = mock_api_client.post(
        "/sandboxes/sess1/files", json={"src_path": "/src", "dest_path": "/dest"}
    )
    assert resp.status_code == 404

    # 400 Case
    mock_global_manager.copy_file_to_container.side_effect = FileNotFoundError(
        "Missing"
    )
    resp = mock_api_client.post(
        "/sandboxes/sess1/files", json={"src_path": "/src", "dest_path": "/dest"}
    )
    assert resp.status_code == 400


@patch("httpx.AsyncClient.post")
def test_execute_tool_success(
    mock_post, mock_api_client, mock_global_manager, mock_container
):
    """Test successful tool execution forwarding."""
    # Setup sandbox
    mock_global_manager.get_or_create_container = AsyncMock()
    mock_global_manager.sandboxes = {
        "sess1": {
            "container": mock_container,
            "tool_server_port": 8080,
            "tool_server_token": "tok",
            "ip_address": "1.2.3.4",
        }
    }
    mock_global_manager._get_ip.return_value = "1.2.3.4"

    # Mock Tool Server Response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": "ok"}
    mock_post.return_value = mock_response

    response = mock_api_client.post(
        "/execute",
        json={
            "session_id": "sess1",
            "agent_id": "ag1",
            "tool_name": "ls",
            "kwargs": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["result"] == "ok"


@patch("httpx.AsyncClient.post")
def test_execute_tool_connect_error(
    mock_post, mock_api_client, mock_global_manager, mock_container
):
    """Test tool execution connection failure fallback."""
    # Setup sandbox
    mock_global_manager.get_or_create_container = AsyncMock()
    mock_global_manager.sandboxes = {
        "sess1": {
            "container": mock_container,
            "tool_server_port": 8080,
            "tool_server_token": "tok",
        }
    }

    # Simulate connection error
    mock_post.side_effect = httpx.RequestError("Connection refused")

    # Mock container logs retrieval
    mock_container.logs.return_value = b"Last logs..."

    response = mock_api_client.post(
        "/execute",
        json={
            "session_id": "sess1",
            "agent_id": "ag1",
            "tool_name": "ls",
            "kwargs": {},
        },
    )

    assert response.status_code == 503
    assert "Connection refused" in response.json()["detail"]
    assert "Last logs" in response.json()["detail"]
