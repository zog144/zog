import copy
import fcntl
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from zog.host_install import state_admission as admission
from zog.host_install.state_contract import StateError, canonical
from zog.host_install.state_initialize import authorize, coordinate, operations
from zog.host_install.state_io import publish
from zog.host_install.state_provision import prepare_tree
from test_state_provision import Context


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        from zog.host_identify.initialization import prepare, load_existing
        self.temp = tempfile.TemporaryDirectory()
        self.c = Context(self.temp.name)
        prepare_tree(self.c, self.c.bundle['bootstrap']['state']['state_volume_id'], service_ids=(0, 0, 0, 0))
        authorize(self.c, self.c.bundle['bootstrap']['initialization']['authorization_id'])
        def worker(action, auth, receipt):
            if action == 'prepare': return prepare(auth['identity_directory'], auth)
            load_existing(auth['identity_directory'], receipt)
            return receipt
        self.receipt = coordinate(self.c, worker, service_ids=(0, 0))['receipt']
        self.ops = Path(self.temp.name, 'host-install/operations')
        self.nonce = 'f' * 64

    def tearDown(self):
        self.c.close(); self.temp.cleanup()

    def response(self):
        return dict(schema=1, kind='zog-host-admission-response', nonce=self.nonce,
                    ok=True, observation=admission.observe(self.c))

    def test_observation_is_read_only_and_does_not_load_key(self):
        def snapshot():
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in Path(self.temp.name).rglob('*') if p.is_file()}
        before = snapshot()
        with patch('zog.host_identify.initialization.load_existing', side_effect=AssertionError('producer must not load key')):
            o = admission.observe(self.c)
        self.assertEqual(o['receipt'], self.receipt)
        self.assertEqual(before, snapshot())
        self.assertEqual(o['identity_action'], 'verify-existing')
        self.assertFalse(o['transport_enabled'])

    def test_existing_and_pending_holds_block_even_if_unparseable(self):
        for name in ['recovery-hold.json', '.pending.recovery-hold.json']:
            with self.subTest(name=name):
                p = self.ops/name;p.write_bytes(b'corrupt');p.chmod(0o600)
                o = admission.observe(self.c)
                self.assertTrue(o['recovery_hold']);self.assertIsNone(o['receipt'])
                self.assertEqual(o['identity_action'], 'block');p.unlink()

    def test_absent_consumption_is_never_created(self):
        p = self.ops/'identity-consumed.json';p.unlink()
        with self.assertRaisesRegex(StateError, 'consumption-unavailable'): admission.observe(self.c)
        self.assertFalse(p.exists())

    def test_pending_publication_requires_coordinator(self):
        p = self.ops/'identity-consumed.json';pending = self.ops/'.pending.identity-consumed.json'
        os.link(p, pending)
        with self.assertRaisesRegex(StateError, 'operation-incomplete'): admission.observe(self.c)
        self.assertTrue(pending.exists());self.assertEqual(p.stat().st_nlink, 2)

    def test_mutation_lock_prevents_observation(self):
        with (self.ops/'.host-install.lock').open('rb') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(StateError, 'operation-busy'): admission.observe(self.c)

    def test_missing_lock_is_not_recreated(self):
        p=self.ops/'.host-install.lock';p.unlink()
        with self.assertRaises(FileNotFoundError): admission.observe(self.c)
        self.assertFalse(p.exists())

    def test_wrong_authorization_or_receipt_refused(self):
        for name in ['identity-authorization.json', 'identity-consumed.json']:
            with self.subTest(name=name):
                p=self.ops/name;old=p.read_bytes();p.write_bytes(b'{}')
                with self.assertRaises(StateError): admission.observe(self.c)
                p.write_bytes(old)

    def test_unsafe_receipt_permissions_refused(self):
        (self.ops/'identity-consumed.json').chmod(0o644)
        with self.assertRaises(StateError): admission.observe(self.c)

    def test_missing_key_does_not_get_regenerated_by_observer(self):
        # Consumer load-existing is mandatory: producer reports ledger, not key health.
        key=Path(self.temp.name,'host-discover/identity/identity.pem');key.unlink()
        self.assertEqual(admission.observe(self.c)['receipt'], self.receipt)
        self.assertFalse(key.exists())

    def test_mount_fault_rejected(self):
        self.c.fault=True
        with self.assertRaisesRegex(StateError, 'mount-changed'): admission.observe(self.c)

    def test_valid_observation_bound_to_consumer(self):
        self.assertEqual(admission.validate_response(self.response(),self.nonce,self.c)['receipt'],self.receipt)

    def test_wrong_nonce_boot_configuration_and_volume_refused(self):
        original=self.response()
        cases=[]
        r=copy.deepcopy(original);r['nonce']='0'*64;cases.append(r)
        for key in ['boot_id','bootstrap_sha256','marker_sha256','state_device','state_inode']:
            r=copy.deepcopy(original);r['observation']['bindings'][key]='wrong';cases.append(r)
        for r in cases:
            with self.subTest(response=r),self.assertRaises(StateError): admission.validate_response(r,self.nonce,self.c)

    def test_consumer_recheck_rejects_late_mount_loss(self):
        r=self.response();self.c.fault=True
        with self.assertRaisesRegex(StateError,'mount-changed'):admission.validate_response(r,self.nonce,self.c)

    def test_unknown_fields_and_capabilities_refused(self):
        for change in ['extra','control','transport','receipt']:
            r=self.response()
            if change=='extra':r['initialize']=True
            if change=='control':r['observation']['control_authorized']=True
            if change=='transport':r['observation']['transport_enabled']=True
            if change=='receipt':r['observation']['receipt']['fingerprint']='bad'
            with self.subTest(change=change),self.assertRaises(StateError):admission.validate_response(r,self.nonce,self.c)

    def test_real_socket_wire_and_fresh_second_hold_query(self):
        from contextlib import contextmanager
        @contextmanager
        def context():yield self.c
        def exchange():
            server,client=socket.socketpair();errors=[]
            def run():
                try:
                    with server:admission.serve_connection(server)
                except BaseException as exc:errors.append(exc)
            with patch.object(admission,'peer_uid',return_value=970),patch.object(admission,'inspect_live',context):
                t=threading.Thread(target=run);t.start()
                with client:
                    client.sendall(canonical(dict(schema=1,kind='zog-host-admission-request',nonce=self.nonce)))
                    client.shutdown(socket.SHUT_WR);response=admission.receive(client,admission.RESPONSE_LIMIT)
                t.join(3);self.assertFalse(t.is_alive());self.assertFalse(errors)
            return admission.validate_response(response,self.nonce,self.c)
        self.assertFalse(exchange()['recovery_hold'])
        (self.ops/'recovery-hold.json').write_bytes(b'held')
        self.assertTrue(exchange()['recovery_hold'])

    def test_client_authentication_over_socketpair(self):
        # Container denies creating pathname sockets. Exercise real stream I/O
        # through a socketpair, substituting connect and service UID ownership.
        from contextlib import contextmanager
        import stat
        @contextmanager
        def context():yield self.c
        server_sock,client_sock=socket.socketpair()
        class Client:
            def __enter__(self):return self
            def __exit__(self,*args):client_sock.close()
            def __getattr__(self,name):return getattr(client_sock,name)
            def connect(self,path):self.path=path
        client=Client()
        with tempfile.TemporaryDirectory() as temp:
            Path(temp).chmod(0o755)
            parent=os.open(temp,os.O_RDONLY|os.O_DIRECTORY)
            values=list(os.fstat(parent));values[0]=stat.S_IFSOCK|0o660;values[3]=1;values[5]=970
            fake_stat=os.stat_result(values)
            errors=[]
            def server():
                try:
                    with server_sock:admission.serve_connection(server_sock)
                except BaseException as exc:errors.append(exc)
            def uid():return 970 if threading.current_thread() is threading.main_thread() else 0
            original_peer=admission.peer_uid
            def peer(connection):
                self.assertEqual(original_peer(connection),0)
                return 0 if threading.current_thread() is threading.main_thread() else 970
            try:
                with patch.object(admission,'directory',return_value=os.dup(parent)),patch.object(admission.os,'stat',return_value=fake_stat),patch.object(admission.os,'geteuid',side_effect=uid),patch.object(admission.os,'getegid',return_value=970),patch.object(admission,'peer_uid',side_effect=peer),patch.object(admission,'inspect_live',context),patch.object(admission.socket,'socket',return_value=client):
                    thread=threading.Thread(target=server);thread.start()
                    result=admission.request_live(self.c)
                    thread.join(3);self.assertFalse(thread.is_alive());self.assertFalse(errors)
                    self.assertEqual(result['receipt'],self.receipt)
                    self.assertTrue(client.path.startswith('/proc/self/fd/'))
            finally:server_sock.close();client_sock.close();os.close(parent)

    def test_live_client_missing_or_untrusted_socket_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp).chmod(0o755)
            def directory(_):return os.open(temp,os.O_RDONLY|os.O_DIRECTORY)
            with patch.object(admission,'directory',side_effect=directory),patch.object(admission.os,'geteuid',return_value=970),patch.object(admission.os,'getegid',return_value=970):
                with self.assertRaises(FileNotFoundError):admission.request_live(self.c)
                p=Path(temp)/'admission.sock';p.write_text('saved response')
                with self.assertRaisesRegex(StateError,'admission-socket'):admission.request_live(self.c)


class WireTests(unittest.TestCase):
    def test_socket_cli_does_not_append_a_second_response(self):
        import io
        from contextlib import redirect_stdout
        from zog.host_install.cli import main
        output=io.StringIO()
        with patch('zog.host_install.cli.serve_stdin',return_value={'status':'served'}),redirect_stdout(output):
            self.assertEqual(main(['state-admission-serve']),0)
        self.assertEqual(output.getvalue(),'')


    def test_kernel_peer_credentials(self):
        left,right=socket.socketpair()
        with left,right: self.assertEqual(admission.peer_uid(left),os.geteuid())

    def test_non_service_uid_rejected_before_inspection(self):
        left,right=socket.socketpair()
        with left,right,patch.object(admission,'peer_uid',return_value=971),patch.object(admission,'inspect_live') as inspect:
            with self.assertRaisesRegex(StateError,'admission-peer'):admission.serve_connection(left)
            inspect.assert_not_called()

    def test_oversize_and_invalid_protocol_refused(self):
        left,right=socket.socketpair()
        with left,right:
            right.sendall(b'x'*4097);right.shutdown(socket.SHUT_WR)
            with self.assertRaisesRegex(StateError,'message-size'):admission.receive(left,4096)
        for r in [dict(schema=2,kind='zog-host-admission-request',nonce='a'*64),dict(schema=1,kind='zog-host-admission-request',nonce='a'*64,action='initialize')]:
            with self.assertRaises(StateError):admission.request_valid(r)

    def test_slow_peer_times_out(self):
        left,right=socket.socketpair()
        with left,right:
            left.settimeout(.01)
            with self.assertRaises(TimeoutError):admission.receive(left,4096)
