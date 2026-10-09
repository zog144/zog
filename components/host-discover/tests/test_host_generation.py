from types import SimpleNamespace
from unittest.mock import patch

from zog.host_discover.managed_transport import Runtime


def state():
    bundle = {
        'installation': {
            'installer_recorded': {
                'foreign_boot_bundle': None,
            }
        }
    }
    return SimpleNamespace(context=SimpleNamespace(bundle=bundle), fail=lambda code: None)


def test_managed_collection_attaches_verified_host_generation():
    runtime = Runtime(state())
    runtime.bootstrap = {'registries': [{'registry_id': 'primary'}]}
    captured = []
    with patch.object(runtime, 'guard'),          patch.object(runtime, 'registry', side_effect=lambda transport, reg, report: captured.append(report)),          patch('zog.host_discover.managed_transport.collect', return_value={
             'version': 1, 'hostname': 'host', 'daemon_version': 'test', 'boot_id': 'boot'
         }),          patch('zog.host_install.state_inspect.host_generation_report', return_value={
             'schema': 1,
             'source': 'verified-host-install-state-v1',
             'installation': {
                 'installation_id': '00000001-0001-4001-8001-000000000001',
                 'record_id': '00000005-0005-4005-8005-000000000005',
                 'record_schema': 1,
                 'operation': 'fresh',
             },
             'selected_slot': 'HOST-A',
             'booted_slot': None,
             'slots': {
                 'HOST-A': {
                     'generation': 'generation-a',
                     'root_partuuid': '00000009-0009-4009-8009-000000000009',
                 },
                 'HOST-B': None,
             },
             'transitional_boot_bundle': None,
         }) as evidence:
        runtime.tick(transport=object())
    assert evidence.call_count == 1
    assert captured[0]['host_generation']['selected_slot'] == 'HOST-A'
    assert captured[0]['host_generation']['booted_slot'] is None


def test_injected_report_is_not_rewritten_or_reinterpreted():
    runtime = Runtime(state())
    runtime.bootstrap = {'registries': [{'registry_id': 'primary'}]}
    supplied = {'version': 1, 'hostname': 'fixture'}
    captured = []
    with patch.object(runtime, 'guard'),          patch.object(runtime, 'registry', side_effect=lambda transport, reg, report: captured.append(report)),          patch('zog.host_install.state_inspect.host_generation_report',
               side_effect=AssertionError('injected fixture report must not consult live STATE')):
        runtime.tick(transport=object(), report=supplied)
    assert captured == [supplied]
