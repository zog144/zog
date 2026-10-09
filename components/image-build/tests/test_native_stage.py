import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from zog.image_build import native_stage as worker
from zog.image_build.box_control_adapter import BuildExecutionPending

@pytest.fixture
def operation(tmp_path, monkeypatch):
    paths = {name: tmp_path/name for name in ('project','catalogue','plan','controller','selection','work')}
    paths['controller'].write_text('{"socket":"/run/test.sock"}')
    selected = SimpleNamespace(generation='base', manifest={'source_built':True,'build_environment_complete':True})
    monkeypatch.setattr(worker, 'read_selection', lambda path: selected)
    monkeypatch.setattr(worker, 'stage_recipes', lambda *args: {'targets':['glibc']})
    monkeypatch.setattr(worker, 'inventory', lambda path: {'recipe':'digest'})
    monkeypatch.setattr(worker, 'configured_runner', lambda *args: object())
    monkeypatch.setattr(worker, 'ImageBuild', lambda **kw: SimpleNamespace(_policy=lambda: {'schema':1}))
    pipeline = Mock(return_value=SimpleNamespace(generation='finished'))
    monkeypatch.setattr(worker, 'pipeline', pipeline)
    return paths, pipeline, selected


def test_pending_resume_and_completed_operation_does_not_resubmit(operation):
    paths, pipeline, _ = operation
    pending = BuildExecutionPending({'request_id':'request','job_id':'job','state':'running',
        'request':{'build_root_id':'root','source_workspace_id':'source','output_workspace_id':'output'}})
    pipeline.side_effect = [pending, SimpleNamespace(generation='finished')]
    with pytest.raises(BuildExecutionPending): worker.run(**paths)
    record = paths['work']/'operation.json'
    assert json.loads(record.read_text())['job_id'] == 'job'
    assert worker.run(**paths)['phase'] == 'complete'
    assert worker.run(**paths)['generation'] == 'finished'
    assert pipeline.call_count == 2


def test_changed_controller_refuses_resume(operation):
    paths, pipeline, _ = operation
    worker.run(**paths)
    paths['controller'].write_text('{"socket":"/run/different.sock"}')
    with pytest.raises(ValueError, match='inputs changed'): worker.run(**paths)
    assert pipeline.call_count == 1


def test_failed_operation_is_not_automatically_retried(operation):
    paths, pipeline, _ = operation
    pipeline.side_effect = RuntimeError('build failed')
    with pytest.raises(RuntimeError): worker.run(**paths)
    assert json.loads((paths['work']/'operation.json').read_text())['phase'] == 'failed'
    with pytest.raises(ValueError, match='explicit review'): worker.run(**paths)
    assert pipeline.call_count == 1


def test_incomplete_base_refused_before_execution(operation):
    paths, pipeline, selected = operation
    selected.manifest['build_environment_complete'] = False
    with pytest.raises(ValueError, match='complete build environment'): worker.run(**paths)
    pipeline.assert_not_called()
