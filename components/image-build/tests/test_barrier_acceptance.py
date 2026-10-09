"""A stale Unix socket left by SIGKILL must not satisfy driver readiness."""
import importlib.util
from pathlib import Path
import socket
import pytest


def test_barrier_readiness_requires_listener(tmp_path, monkeypatch):
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except PermissionError:
        pytest.skip('execution environment denies Unix sockets; run on the disposable host')
    probe.close()
    directory = Path(__file__).parents[1]/'acceptance'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('barrier_acceptance', directory/'barrier_provenance.py')
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    path = tmp_path/'controller.sock'
    assert not driver.listening(path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
    assert path.exists() and not driver.listening(path)
    path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(1)
        assert driver.listening(path)
