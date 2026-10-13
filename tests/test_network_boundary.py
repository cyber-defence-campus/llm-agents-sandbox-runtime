"""Reject incompatible reuse before lifecycle or network mutations."""
from unittest.mock import AsyncMock
import pytest
from sandbox_runtime.manager import SandboxBoundaryConflict, network_boundary


def scoped(container):
    container.attrs['Config']['Env'] += ['AGENT_EGRESS_CIDR=172.28.0.0/16',
        'AGENT_RESTRICTED_CIDR=172.28.3.0/24', 'AGENT_ALLOWED_ADDRESS=172.28.3.10',
        'AGENT_DROP_NET_ADMIN=1']
    container.attrs['NetworkSettings']['Networks']['lab-net'] = {'IPAddress':'172.28.3.5'}
    return container


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [
    {'egress_cidr':'172.28.0.0/16'},
    {'restricted_cidr':'172.28.3.0/24','allowed_address':'172.28.3.10'}])
async def test_unscoped_container_cannot_accept_late_boundary(sandbox_manager, mock_container, options):
    sandbox_manager.docker.containers.get.return_value = mock_container
    sandbox_manager._find_existing = AsyncMock()
    sandbox_manager._create_new = AsyncMock()
    sandbox_manager._ensure_networks = AsyncMock()
    with pytest.raises(SandboxBoundaryConflict):
        await sandbox_manager.get_or_create_container('test_session', **options)
    sandbox_manager._find_existing.assert_not_called()
    sandbox_manager._create_new.assert_not_called()
    sandbox_manager._ensure_networks.assert_not_called()
    mock_container.start.assert_not_called()
    mock_container.remove.assert_not_called()


@pytest.mark.asyncio
async def test_identical_scope_reuses_container_and_default_calls_keep_it(sandbox_manager, mock_container):
    scoped(mock_container)
    sandbox_manager.docker.containers.get.return_value = mock_container
    sandbox_manager._find_existing = AsyncMock(return_value=mock_container)
    sandbox_manager._ensure_networks = AsyncMock()
    result = await sandbox_manager.get_or_create_container('test_session', networks=['lab-net'],
        egress_cidr='172.28.0.0/16', restricted_cidr='172.28.3.0/24', allowed_address='172.28.3.10')
    assert result is mock_container
    sandbox_manager._find_existing.assert_awaited_once_with('test_session', preserve_on_failure=True)
    sandbox_manager._find_existing.reset_mock()
    assert await sandbox_manager.get_or_create_container('test_session') is mock_container
    sandbox_manager._find_existing.assert_awaited_once_with('test_session', preserve_on_failure=True)
    assert network_boundary(mock_container)['allowed_address']=='172.28.3.10'


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [{'allowed_address':'172.28.3.11','restricted_cidr':'172.28.3.0/24'},
                                    {'networks':['another-net']}])
async def test_changed_scope_or_new_interface_cannot_expand_existing_boundary(sandbox_manager,mock_container,options):
    scoped(mock_container)
    sandbox_manager.docker.containers.get.return_value=mock_container
    sandbox_manager._find_existing=AsyncMock()
    sandbox_manager._ensure_networks=AsyncMock()
    with pytest.raises(SandboxBoundaryConflict):
        await sandbox_manager.get_or_create_container('test_session', **options)
    sandbox_manager._find_existing.assert_not_called()
    sandbox_manager._ensure_networks.assert_not_called()


@pytest.mark.asyncio
async def test_scoped_unhealthy_container_is_retained(sandbox_manager,mock_container):
    scoped(mock_container)
    sandbox_manager.docker.containers.get.return_value=mock_container
    sandbox_manager._extract_container_info=lambda _:('172.17.0.2',1234,'fixture-token')
    sandbox_manager._healthy_after=AsyncMock(return_value=False)
    sandbox_manager._restart_sandbox=AsyncMock(return_value=None)
    sandbox_manager._remove_container=AsyncMock()
    sandbox_manager._create_new=AsyncMock()
    with pytest.raises(SandboxBoundaryConflict):
        await sandbox_manager.get_or_create_container('test_session')
    sandbox_manager._remove_container.assert_not_called()
    sandbox_manager._create_new.assert_not_called()


@pytest.mark.asyncio
async def test_scoped_identity_change_is_not_replacement_success(sandbox_manager,mock_container):
    from types import SimpleNamespace
    scoped(mock_container)
    sandbox_manager.docker.containers.get.return_value=mock_container
    sandbox_manager._find_existing=AsyncMock(return_value=SimpleNamespace(id='different'))
    sandbox_manager._ensure_networks=AsyncMock()
    with pytest.raises(SandboxBoundaryConflict):
        await sandbox_manager.get_or_create_container('test_session')
    sandbox_manager._ensure_networks.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('options',[{'egress_cidr':'not-a-network'},
    {'egress_cidr':'fd00::/64'}, {'restricted_cidr':'172.28.3.0/24','allowed_address':'172.29.0.10'}])
async def test_invalid_scope_is_rejected_before_inspection(sandbox_manager,options):
    with pytest.raises(ValueError):
        await sandbox_manager.get_or_create_container('test_session', **options)
    sandbox_manager.docker.containers.get.assert_not_called()


def test_api_conflict_is409_without_network_mutation(mock_api_client,mock_global_manager):
    mock_global_manager.get_or_create_container=AsyncMock(side_effect=SandboxBoundaryConflict('incompatible boundary'))
    result=mock_api_client.post('/sandboxes',json={'session_id':'existing','egress_cidr':'172.28.0.0/16'})
    assert result.status_code==409


def test_api_declares_configuration_not_connectivity(mock_api_client,mock_global_manager,mock_container):
    scoped(mock_container)
    mock_global_manager.get_or_create_container=AsyncMock(return_value=mock_container)
    mock_global_manager._get_ip.return_value='172.17.0.2'
    mock_global_manager.sandboxes={'scoped':{'tool_server_port':1234,'tool_server_token':'fixture','container':mock_container}}
    result=mock_api_client.post('/sandboxes',json={'session_id':'scoped','networks':['lab-net'],'egress_cidr':'172.28.0.0/16'})
    assert result.status_code==200
    assert result.json()['network_boundary']['egress_cidr']=='172.28.0.0/16'
    assert result.json()['network_addresses']=={'lab-net':'172.28.3.5'}
    assert 'reachable' not in result.json()


def test_network_inspection_cannot_create_or_restart(mock_api_client,mock_global_manager,mock_container):
    scoped(mock_container)
    mock_global_manager.docker.containers.get.return_value=mock_container
    result=mock_api_client.get('/sandboxes/test_session/network')
    assert result.status_code==200
    assert result.json()['provenance']=='container_configuration'
    assert result.json()['network_boundary']['allowed_address']=='172.28.3.10'
    assert 'token' not in str(result.json())
    mock_global_manager.get_or_create_container.assert_not_called()
    mock_container.start.assert_not_called();mock_container.restart.assert_not_called()
    mock_container.exec_run.assert_not_called()


def test_absent_network_inspection_is404_without_replacement(mock_api_client,mock_global_manager):
    from docker.errors import NotFound
    mock_global_manager.docker.containers.get.side_effect=NotFound('missing')
    result=mock_api_client.get('/sandboxes/missing/network')
    assert result.status_code==404
    mock_global_manager.get_or_create_container.assert_not_called()
