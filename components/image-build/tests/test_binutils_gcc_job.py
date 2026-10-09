"""Continuation must not dispatch GCC before linker acceptance."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('binutils_gcc_job', Path(__file__).parents[1] / 'jobs/binutils_gcc.py')
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

@pytest.mark.parametrize('failure', ['binutils', 'preflight', None])
def test_gcc_dispatch_requires_binutils_and_preflight(tmp_path, monkeypatch, failure):
    from contextlib import nullcontext
    base = SimpleNamespace(generation='base', root=tmp_path/'base/root',
                           manifest={'source_built': True, 'build_environment_complete': True})
    monkeypatch.setattr(job, 'read_selection', lambda _: base)
    monkeypatch.setattr(job, 'replacement_records', lambda _: {'identity': 'old'})
    monkeypatch.setattr(job, 'stage_recipes', lambda source, cat, dest: {'targets': [dest.name]})
    monkeypatch.setattr(job, 'inventory', lambda _: [])
    monkeypatch.setattr(job, 'configured_runner', lambda *a: None)
    monkeypatch.setattr(job, 'recorded_root', lambda path, inputs, action: path)
    monkeypatch.setattr(job, 'successful_execution', lambda _: {'exit_code': 0, 'cleanup_complete': True})
    builder = SimpleNamespace(_policy=lambda: {}, locked=nullcontext,
                             _publish=lambda *a: SimpleNamespace(generation='linker', root=tmp_path/'linker'))
    monkeypatch.setattr(job, 'ImageBuild', lambda **kw: builder)
    monkeypatch.setattr(job, 'wait_for', lambda w, label, action: action())
    calls = []
    def pipeline(builder, selection, targets, operation):
        calls.append(targets[0])
        if failure == 'binutils': raise RuntimeError('binutils failed')
        return SimpleNamespace(generation=targets[0], root=tmp_path/targets[0])
    monkeypatch.setattr(job, 'pipeline', pipeline)
    def verify(*a):
        if failure == 'preflight': raise RuntimeError('preflight failed')
        return {'verified': True}
    monkeypatch.setattr(job, 'verify', verify)
    args = (tmp_path, tmp_path/'project/package', 'controller', 'selection', 'ownership', tmp_path/'work', None)
    if failure:
        with pytest.raises(RuntimeError, match=failure): job.run(*args)
        assert calls == ['recipes-binutils']
    else:
        result = job.run(*args)
        assert calls == ['recipes-binutils', 'recipes-gcc']
        assert result['self_hosted'] is False
