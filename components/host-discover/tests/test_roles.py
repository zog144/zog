import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from zog.host_discover.roles import Controller, validate
from zog.host_discover.daemon import announce
from zog.host_identify import storage,signatures
from test_signed_daemon import configuration,Response


def intent(selected=True,revision=1):
    return {'desired':{'version':1,'revision':revision,'selected':selected,'endpoint':'https://mirror.example.test' if selected else '',
        'retain_archives':True,'lease_expires_at':int(time.time())+900},'candidates':[]}

class Adapter:
    def __init__(self):self.starts=[];self.stops=[];self.present=True;self.alive=True;self.serving=True;self.failure=False;self.issued=0
    def available(self):return self.present
    def issue(self):self.issued+=1;return str(uuid.uuid4())
    def start(self,request):
        self.starts.append(request)
        if self.failure:raise RuntimeError('DO-NOT-LOG')
        return 'runtime-1'
    def stop(self,request,runtime):self.stops.append((request,runtime))
    def running(self,runtime):return self.alive
    def ready(self,*args):return self.serving


def test_restart_idempotence_lease_expiry_and_retained_archives(configuration,tmp_path):
    adapter=Adapter();host=str(uuid.uuid4());c=Controller(configuration,adapter)
    archive=tmp_path/'retained-archive.tar';archive.write_text('retained')
    assert c.tick(host,intent())['state']=='ready'
    assert len(adapter.starts)==1
    assert Controller(configuration,adapter).tick()['state']=='ready'
    assert len(adapter.starts)==1
    with patch('zog.host_discover.roles.time.time',return_value=time.time()+901):assert c.tick()['state']=='stopped'
    assert len(adapter.stops)==1;assert archive.read_text()=='retained'
    assert c.path.stat().st_mode&0o777==0o600


def test_assignment_removal_restart_and_rollback(configuration):
    a=Adapter();c=Controller(configuration,a);host=str(uuid.uuid4())
    c.tick(host,intent());assert c.tick(host,intent(False,2))['state']=='stopped'
    assert len(a.stops)==1
    with pytest.raises(ValueError):c.tick(host,intent(True,1))
    assert c.tick(host,intent(True,3))['state']=='ready';assert a.issued==2
    value=intent(True,3);value['desired']['endpoint']='https://different.example.test'
    with pytest.raises(ValueError):c.tick(host,value)


def test_uncertain_start_reuses_identity_and_withdraw_cancels(configuration):
    a=Adapter();a.failure=True;c=Controller(configuration,a);host=str(uuid.uuid4())
    assert c.tick(host,intent())['state']=='failed'
    Controller(configuration,a).tick();assert len(set(a.starts))==1
    c.tick(withdraw=True);assert a.stops[0][0]==a.starts[0]
    assert c.tick()['state']=='stopped'


def test_blocked_missing_bridge_application_and_failed_probe(configuration):
    host=str(uuid.uuid4());c=Controller(configuration)
    assert c.tick(host,intent())['reason']=='bridge-unconfigured'
    a=Adapter();a.present=False;c=Controller(configuration,a)
    assert c.tick()['reason']=='application-missing';assert not a.starts
    a.present=True;a.serving=False;assert c.tick()['state']=='running'
    a.alive=False;assert c.tick()['state']=='failed'


def test_malformed_roles_cannot_start(configuration):
    a=Adapter();c=Controller(configuration,a);d=intent();d['desired']['retain_archives']=False
    with pytest.raises(ValueError):c.tick(str(uuid.uuid4()),d)
    assert not a.starts
    d=intent();d['desired']['endpoint']='http://evil.example'
    with pytest.raises(ValueError):validate(d)


def test_station_login_sent_only_after_binding_and_protected_file(configuration):
    root=Path(configuration['identity_directory']);source=root/'station-login.json'
    storage.atomic(source,json.dumps({'username':'station-admin','password':'SYNTHETIC-TEST-SECRET'}).encode())
    configuration['station_login_file']=str(source)
    key=storage.load_key(root);fp=signatures.fingerprint(key.public_key());host=str(uuid.uuid4())
    with patch('urllib.request.OpenerDirector.open',return_value=Response({'status':'pending'},202)) as open:
        announce(configuration,{'version':1});assert b'SYNTHETIC' not in open.call_args.args[0].data
    storage.atomic(root/'binding.json',json.dumps({'host_id':host,'fingerprint':fp}).encode())
    with patch('urllib.request.OpenerDirector.open',return_value=Response({'version':2,'host_id':host,'archive':None,'mirror_roles':intent(False,0)})) as open:
        announce(configuration,{'version':1});request=open.call_args.args[0]
        assert json.loads(request.data)['station_login']['password']=='SYNTHETIC-TEST-SECRET'
        signatures.verify(request.full_url,'POST',dict(request.header_items()),request.data,key.public_key(),host)
        source.chmod(0o644);announce(configuration,{'version':1});assert 'station_login' not in json.loads(open.call_args.args[0].data)
        configuration['station_login_withdraw']=True;announce(configuration,{'version':1});assert json.loads(open.call_args.args[0].data)['station_login'] is None


def test_box_bridge_required_members_and_probe():
    from zog.host_discover.box_bridge import BoxBridge
    from unittest.mock import Mock
    bridge=object.__new__(BoxBridge);bridge.control=Mock();bridge.required=['server','refresh-scheduler']
    p=lambda name,state:{'program':name,'status':'observed','observation':{'active_state':state}}
    bridge.control.observe_application_runtime.return_value={'status':'observed','programs':[p('server','active')]}
    assert bridge.running('r') is None
    bridge.control.observe_application_runtime.return_value['programs'].append(p('refresh-scheduler','active'))
    assert bridge.running('r')
    bridge.control.observe_application_runtime.return_value['status']='partial';assert bridge.running('r') is None


def test_confirmed_failure_restarts_after_backoff_but_unknown_observation_does_not(configuration):
    a=Adapter();c=Controller(configuration,a);host=str(uuid.uuid4());c.tick(host,intent())
    a.alive=None;assert c.tick()['reason']=='runtime-unavailable';assert not a.stops
    a.alive=False;assert c.tick()['state']=='failed';assert len(a.stops)==1
    a.alive=True;assert c.tick()['state']=='failed';assert len(a.starts)==1
    with patch('zog.host_discover.roles.time.time',return_value=time.time()+61):assert c.tick()['state']=='ready'
    assert len(a.starts)==2;assert a.starts[0]!=a.starts[1]


def test_failed_stop_retries_same_owned_runtime(configuration):
    a=Adapter();c=Controller(configuration,a);host=str(uuid.uuid4());c.tick(host,intent())
    with patch.object(a,'stop',side_effect=RuntimeError('fixture stop unavailable')):
        assert c.tick(host,intent(False,2))['state']=='failed'
        assert c.load()['runtime_id']=='runtime-1'
    assert Controller(configuration,a).tick()['state']=='stopped'
    assert a.stops[0][1]=='runtime-1'


def test_old_response_cannot_overwrite_shared_intent(configuration):
    a=Adapter();c=Controller(configuration,a);host=str(uuid.uuid4());c.tick(host,intent(True,2))
    target=Path(configuration['credential_directory'])/'mirror-intent.json';original=target.read_bytes()
    with pytest.raises(ValueError):Controller(configuration,a).tick(host,intent(False,1))
    assert target.read_bytes()==original
    assert target.stat().st_mode&0o777==0o640
