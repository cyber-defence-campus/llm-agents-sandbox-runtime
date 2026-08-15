import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sandbox_runtime.manager import SandboxManager
from sandbox_runtime.api import app
from fastapi.testclient import TestClient


@pytest.fixture
def mock_docker_client():
    with patch("docker.from_env") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.id = "test_container_id"
    container.name = "platform-test_session"
    container.status = "running"
    container.attrs = {
        "Config": {
            "Env": [
                "TOOL_SERVER_PORT=1234",
                "TOOL_SERVER_TOKEN=token123",
                "PYTHONUNBUFFERED=1",
            ]
        },
        "NetworkSettings": {"Networks": {"platform_net": {"IPAddress": "172.17.0.2"}}},
    }
    return container


@pytest.fixture
def sandbox_manager(mock_docker_client):
    manager = SandboxManager()
    manager.docker = mock_docker_client
    return manager


@pytest.fixture
def mock_api_client():
    return TestClient(app)


@pytest.fixture
def mock_global_manager():
    """Patches the global sandbox_manager instance used by API"""
    with patch("sandbox_runtime.api.sandbox_manager") as mock:
        yield mock
