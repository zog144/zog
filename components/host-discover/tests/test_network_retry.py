import copy
import errno
import http.client
import io
import socket
import ssl
import urllib.error
import pytest
from zog.host_install.state_contract import StateError
from zog.host_discover import beacon
from zog.host_discover.retry import RetryableTransport, classify
from test_supervised_beacon import environment, current
from test_managed_admission import Station


@pytest.mark.parametrize('error',[
    TimeoutError(), ConnectionRefusedError(), ConnectionResetError(),
    urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN,'temporary')),
    OSError(errno.ENETUNREACH,'unreachable'),http.client.IncompleteRead(b'partial'),
    *[urllib.error.HTTPError('https://example.invalid',n,'test',{},io.BytesIO()) for n in (408,429,502,503,504)]])
def test_explicit_retryable_classification(error):
    with pytest.raises(RetryableTransport):classify(error)


@pytest.mark.parametrize('error',[
    ssl.SSLCertVerificationError(),urllib.error.URLError(ssl.SSLError()),
    OSError(errno.EIO,'storage'),PermissionError(),
    urllib.error.URLError(socket.gaierror(socket.EAI_NONAME,'bad name')),
    *[urllib.error.HTTPError('https://example.invalid',n,'test',{},io.BytesIO()) for n in (301,400,401,403,404,409,500)]])
def test_other_errors_never_retry(error):
    with pytest.raises(StateError) as e:classify(error)
    assert not isinstance(e.value,RetryableTransport)


def test_outage_before_enrollment_then_automatic_recovery(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station()
    class Down:
        def post(self,*a):raise RetryableTransport()
    try:
        for _ in range(3):
            with pytest.raises(RetryableTransport):runtime.tick(Down(),{'version':1})
            assert current(state)['fault'] is None and runtime.key is not None
        station.approved=True;runtime.tick(station,{'version':1})
        assert runtime.sessions['primary']['epoch']==1
        runtime.finish();assert current(state)['run'] is None
    finally:runtime.close()


def test_lost_session_retries_same_pending_request(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True
    original=station.post;lost={}
    def lose(url,payload,*args):
        result=original(url,payload,*args)
        if url.endswith('/managed-session/'):
            lost.update(payload=copy.deepcopy(payload),result=result);raise RetryableTransport()
        return result
    station.post=lose
    try:
        with pytest.raises(RetryableTransport):runtime.tick(station,{'version':1})
        assert runtime.saved['registries']['primary']['pending']==lost['payload']
        assert current(state)['fault'] is None
        def retry(url,payload,*args):
            if url.endswith('/managed-session/'):
                assert payload==lost['payload'];return lost['result']
            return original(url,payload,*args)
        station.post=retry;runtime.tick(station,{'version':1})
        assert runtime.sessions['primary']['epoch']==1
        runtime.finish()
    finally:runtime.close()


def test_expired_uncertain_session_is_not_discarded(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True
    original=station.post
    def lost(url,payload,*a):
        result=original(url,payload,*a)
        if url.endswith('/managed-session/'):raise RetryableTransport()
        return result
    station.post=lost
    with pytest.raises(RetryableTransport):runtime.tick(station,{'version':1})
    pending=copy.deepcopy(runtime.saved['registries']['primary']['pending'])
    class Expired:
        def post(self,*a):raise StateError('managed-http-refused','409 recovery required')
    try:
        with pytest.raises(StateError):runtime.tick(Expired(),{'version':1})
        assert runtime.saved['registries']['primary']['pending']==pending
        assert current(state)['fault'] is not None
    finally:runtime.close()


def test_storage_fault_during_outage_still_latches(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open()
    class Down:
        def post(self,*a):state.fault='state-io-failure';raise RetryableTransport()
    try:
        with pytest.raises(StateError) as e:runtime.tick(Down(),{'version':1})
        assert not isinstance(e.value,RetryableTransport) and runtime.key is None
        assert current(state)['run'] is not None
    finally:runtime.close()


def test_clean_shutdown_with_pending_retry_preserves_request(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True
    original=station.post
    def down(url,payload,*a):
        if url.endswith('/managed-session/'):raise RetryableTransport()
        return original(url,payload,*a)
    station.post=down
    with pytest.raises(RetryableTransport):runtime.tick(station,{'version':1})
    pending=copy.deepcopy(runtime.saved['registries']['primary']['pending']);runtime.finish()
    assert current(state)['fault'] is None and current(state)['run'] is None
    runtime=beacon.Beacon(state).open()
    assert runtime.saved['registries']['primary']['pending']==pending
    station.post=original;runtime.tick(station,{'version':1});runtime.finish()


def test_backoff_is_capped_health_checked_and_interruptible(monkeypatch):
    class Stop:
        time=0;done=False;waits=[]
        def is_set(self):return self.done
        def wait(self,delay):
            self.waits.append(delay);self.time+=delay
            if self.time>=130:self.done=True
    stop=Stop()
    class Runtime:
        checks=0;attempts=0
        def guard(self):self.checks+=1
        def fail(self,e):raise e
        def tick(self):self.attempts+=1;raise RetryableTransport()
    runtime=Runtime();original=beacon.wait_checked
    monkeypatch.setattr(beacon,'wait_checked',lambda r,s,d:original(r,s,d,clock=lambda:stop.time))
    monkeypatch.setattr(beacon.random,'uniform',lambda *a:1)
    assert beacon.loop(runtime,stop)=='managed-beacon-stopped'
    assert max(stop.waits)<=5 and runtime.checks>runtime.attempts
    assert runtime.attempts<10


def test_once_returns_retry_pending_without_sleep():
    class R:
        def tick(self):raise RetryableTransport()
    class Stop:
        def is_set(self):return False
    assert beacon.loop(R(),Stop(),True)=='retry-pending'


def test_hold_introduced_during_backoff_blocks(environment):
    state,observation,_=environment;runtime=beacon.Beacon(state).open()
    class Stop:
        now=0
        def is_set(self):return False
        def wait(self,delay):self.now+=delay;observation['recovery_hold']=True
    stop=Stop()
    try:
        with pytest.raises(StateError):beacon.wait_checked(runtime,stop,60,clock=lambda:stop.now)
        assert runtime.key is None and current(state)['fault'] is not None
    finally:runtime.close()
