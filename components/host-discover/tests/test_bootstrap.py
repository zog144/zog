import copy
import json
from pathlib import Path
import pytest
from zog.host_discover import bootstrap, daemon
from zog.host_install.state_contract import StateError

ROOT=Path(__file__).parent/'fixtures/host-install'
B=json.loads((ROOT/'bundle.json').read_text())
SCENARIOS=json.loads((ROOT/'scenarios.json').read_text())


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s['name'] for s in SCENARIOS])
def test_authoritative_scenarios_never_admit_transport(scenario):
    bundle=copy.deepcopy(B)
    # Scenario records contain trusted synthetic evidence, never live tokens.
    from zog.host_install.state_inspect import assess_mount
    evidence=copy.deepcopy(scenario['evidence'])
    try:assess_mount(scenario['mounts'],scenario['devices'],bundle['bootstrap']['state'],'8:1')
    except StateError:evidence['mount_verified']=False
    result=bootstrap.evaluate(bundle,evidence)
    assert result['identity_action']==scenario['expected']['identity_action']
    assert result['code']==scenario['expected']['code']
    assert result['policy_control_allowed']==scenario['expected']['control_allowed']
    assert result['live_admission'] is False
    assert result['remote_control_enabled'] is False


def test_complete_records_and_old_partial_rejection():
    assert bootstrap.evaluate(B,SCENARIOS[0]['evidence'])['identity_action']=='load-existing'
    incomplete=copy.deepcopy(B)
    del incomplete['installation']['installer_recorded']['root_partuuid']
    with pytest.raises(StateError): bootstrap.evaluate(incomplete, SCENARIOS[0]['evidence'])
    with pytest.raises(StateError): bootstrap.parse(b'{"schema":1,"schema":2}')
    with pytest.raises(StateError): bootstrap.parse(b'{"value":1.5}')
    with pytest.raises(StateError): bootstrap.parse(b' '*65537)


@pytest.mark.parametrize('field,value',[('schema',2),('schema',True),('profile','unknown'),('mode','automatic'),('configuration_revision',False)])
def test_unknown_contract_blocked(field,value):
    bundle=copy.deepcopy(B);bundle['bootstrap'][field]=value
    with pytest.raises(StateError):bootstrap.evaluate(bundle,SCENARIOS[0]['evidence'])


@pytest.mark.parametrize('configuration',[
    {'identity_directory':'/state/host-discover/identity'},
    {'host_bootstrap':None,'identity_directory':'/tmp/identity'},
    {'state_contract':'','identity_directory':'/tmp/identity'},
    {'host_bootstrap':'/etc/zog/host-install/bootstrap.json','identity_directory':'/tmp/identity'},
    {'state_contract':'state-contract-v1','identity_directory':'/tmp/identity'}])
def test_proposed_contract_never_falls_back_to_legacy_network(configuration,monkeypatch):
    config={'server':'https://registry.example.invalid','credential_directory':'/run/host-discover/archive',**configuration}
    from zog.host_identify import storage
    monkeypatch.setattr(storage,'load_key',lambda *args:pytest.fail('must not initialize'))
    monkeypatch.setattr(daemon.urllib.request,'build_opener',lambda *args:pytest.fail('must not contact network'))
    with pytest.raises(ValueError):daemon.announce(config,{})


def test_existing_only_fingerprint_does_not_create_missing_key(tmp_path):
    root=tmp_path/'identity';root.mkdir(mode=0o700)
    cfg={'identity_directory':str(root),'credential_directory':str(tmp_path/'credentials'),
         'server':'https://registry.example.invalid','identity_mode':'existing-only'}
    with pytest.raises(daemon.IdentityUnavailableError):daemon.identity_key(cfg)
    assert list(root.iterdir())==[]


def test_missing_existing_key_exits_without_reconciling_roles(tmp_path,monkeypatch):
    import sys
    from zog.host_discover import roles
    root=tmp_path/'identity';root.mkdir(mode=0o700)
    cfg={'identity_directory':str(root),'credential_directory':str(tmp_path/'credentials'),
         'server':'https://registry.example.invalid','identity_mode':'existing-only'}
    path=tmp_path/'configuration.json';path.write_text(json.dumps(cfg))
    monkeypatch.setattr(sys,'argv',['host-discover','--configuration',str(path),'--once'])
    monkeypatch.setattr(roles.Controller,'tick',lambda *args,**kwargs:pytest.fail('must not reconcile roles'))
    monkeypatch.setattr(daemon,'collect',lambda _: {})
    with pytest.raises(SystemExit):daemon.main()
    assert not (root/'identity.pem').exists()
