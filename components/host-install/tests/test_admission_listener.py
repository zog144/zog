"""Real systemd-style inherited listener; no filesystem/identity bypass in CLI."""
import os
import socket
import signal
from pathlib import Path
import pytest
from zog.host_install.state_contract import StateError
from zog.host_install.state_admission import serve_listener


def test_listener_requires_systemd_activation(monkeypatch):
    monkeypatch.delenv('LISTEN_PID',raising=False)
    with pytest.raises(StateError,match='admission-activation'):serve_listener()


def test_listener_continues_after_bad_connection(tmp_path):
    path=str(tmp_path/'listener.sock');listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(path);listener.listen(4)
    pid=os.fork()
    if pid==0:
        try:
            os.dup2(listener.fileno(),3);os.environ['LISTEN_PID']=str(os.getpid());os.environ['LISTEN_FDS']='1'
            def handler(c):
                data=c.recv(10)
                if data==b'bad':raise ValueError('invalid request')
                if data==b'end':raise SystemExit(0)
                c.sendall(b'ok')
            serve_listener(handler)
        except SystemExit:os._exit(0)
        except BaseException:os._exit(1)
    listener.close()
    try:
        for data,expected in [(b'bad',b''),(b'valid',b'ok'),(b'end',b'')]:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as c:
                c.settimeout(5);c.connect(path);c.sendall(data);c.shutdown(socket.SHUT_WR);assert c.recv(10)==expected
        _,status=os.waitpid(pid,0);assert os.waitstatus_to_exitcode(status)==0
    finally:
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
