import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
from docker.errors import NotFound, DockerException
from sandbox_runtime.manager import SandboxManager


@pytest.mark.asyncio
async def test_get_or_create_container_existing_healthy(
    sandbox_manager, mock_container
):
    """Test retrieving an existing healthy container."""
    sandbox_manager._find_existing = AsyncMock(return_value=mock_container)
    sandbox_manager._create_new = AsyncMock()

    container = await sandbox_manager.get_or_create_container("test_session")

    assert container == mock_container
    sandbox_manager._find_existing.assert_called_once_with("test_session")
    sandbox_manager._create_new.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_container_new(sandbox_manager, mock_container):
    """Test creating a new container when none exists."""
    sandbox_manager._find_existing = AsyncMock(return_value=None)
    sandbox_manager._create_new = AsyncMock(return_value=mock_container)

    container = await sandbox_manager.get_or_create_container("test_session")

    assert container == mock_container
    sandbox_manager._create_new.assert_called_once_with("test_session")


@pytest.mark.asyncio
async def test_find_existing_healthy(sandbox_manager, mock_container):
    """Test finding an existing healthy container."""
    # Setup mocks
    mock_container.status = "running"
    sandbox_manager.docker.containers.get.return_value = mock_container
    sandbox_manager._check_health = AsyncMock(return_value=True)

    container = await sandbox_manager._find_existing("test_session")

    assert container == mock_container
    mock_container.reload.assert_called()
    assert "test_session" in sandbox_manager.sandboxes


@pytest.mark.asyncio
async def test_find_existing_stopped(sandbox_manager, mock_container):
    """Test restarting a stopped container."""
    mock_container.status = "exited"
    sandbox_manager.docker.containers.get.return_value = mock_container
    sandbox_manager._check_health = AsyncMock(return_value=True)

    await sandbox_manager._find_existing("test_session")

    mock_container.start.assert_called_once()


@pytest.mark.asyncio
async def test_find_existing_unhealthy(sandbox_manager, mock_container):
    """Test removing an unhealthy container."""
    sandbox_manager.docker.containers.get.return_value = mock_container
    sandbox_manager._check_health = AsyncMock(return_value=False)
    sandbox_manager._remove_container = AsyncMock()

    container = await sandbox_manager._find_existing("test_session")

    assert container is None
    sandbox_manager._remove_container.assert_called_once_with(mock_container)


@pytest.mark.asyncio
async def test_find_existing_missing_config(sandbox_manager, mock_container):
    """Test container with missing env vars."""
    mock_container.attrs["Config"]["Env"] = []  # Missing envs
    sandbox_manager.docker.containers.get.return_value = mock_container
    sandbox_manager._remove_container = AsyncMock()

    container = await sandbox_manager._find_existing("test_session")

    assert container is None
    sandbox_manager._remove_container.assert_called_once()


@pytest.mark.asyncio
async def test_create_new_success(sandbox_manager, mock_container):
    """Test successful creation of a new sandbox."""
    # Setup
    sandbox_manager.docker.containers.get.side_effect = NotFound("Not found")
    sandbox_manager.docker.containers.run.return_value = mock_container
    sandbox_manager._check_health = AsyncMock(return_value=True)
    sandbox_manager._wait_for_health = AsyncMock()

    container = await sandbox_manager._create_new("test_session")

    assert container == mock_container
    sandbox_manager.docker.containers.run.assert_called_once()
    assert "test_session" in sandbox_manager.sandboxes


@pytest.mark.asyncio
async def test_create_new_failure(sandbox_manager):
    """Test failure during creation cleans up."""
    sandbox_manager.docker.containers.get.side_effect = NotFound("Not found")
    sandbox_manager.docker.containers.run.side_effect = DockerException("Boom")
    sandbox_manager._remove_container = AsyncMock()

    with pytest.raises(RuntimeError):
        await sandbox_manager._create_new("test_session")


@pytest.mark.asyncio
async def test_copy_file(sandbox_manager, mock_container):
    """Test file injection."""
    sandbox_manager._find_existing = AsyncMock(return_value=mock_container)

    with (
        patch("builtins.open", mock_open(read_data=b"data")),
        patch("tarfile.open") as mock_tar,
    ):
        await sandbox_manager.copy_file(
            "test_session", "/src/file.txt", "/dest/file.txt"
        )

        mock_container.exec_run.assert_called_once_with("mkdir -p /dest")
        mock_container.put_archive.assert_called_once()


@pytest.mark.asyncio
async def test_check_health(sandbox_manager):
    """Test health check logic."""
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}
        mock_get.return_value = mock_response

        is_healthy = await sandbox_manager._check_health("1.2.3.4", 8080, "token")
        assert is_healthy is True

        # Test failure
        mock_get.side_effect = Exception("error")
        is_healthy = await sandbox_manager._check_health("1.2.3.4", 8080, "token")
        assert is_healthy is False


def test_extract_container_info(sandbox_manager, mock_container):
    """Test parsing container info."""
    ip, port, token = sandbox_manager._extract_container_info(mock_container)
    assert ip == "172.17.0.2"
    assert port == 1234
    assert token == "token123"


def test_parse_volumes(sandbox_manager):
    """Test volume parsing."""
    with patch(
        "sandbox_runtime.manager.AGENT_SANDBOX_VOLUMES", "/host/path:/container/path:rw"
    ):
        volumes = sandbox_manager._parse_volumes()
        assert volumes == {"/host/path": {"bind": "/container/path", "mode": "rw"}}
