"""Inspection cannot interfere with the durable execution/recovery protocol."""
import hashlib
import json
from pathlib import Path
import pytest
from zog.image_build.trace_records import capture_identity, capture_request, import_diagnostic
from zog.image_build.runner import BuildExecutionRequest


def test_identity_is_immutable_and_links_are_explicit(tmp_path):
    args=dict(attempt_id='attempt',command_id='probe',package='gcc',stage_id='final',phase='test',command_index=0)
    log=tmp_path/'probe.log'
    assert capture_identity(log,**args)
    saved=log.with_suffix('.trace.json').read_bytes()
    assert not capture_identity(log,**dict(args,stage_id='changed'))
    assert log.with_suffix('.trace.json').read_bytes()==saved
    with pytest.raises(ValueError):
        capture_identity(log,**args,relationships=[{'relation':'retry-of','target':{'attempt_id':'attempt','command_id':'probe'}}])
    with pytest.raises(ValueError):
        capture_identity(log,**args,receipts=['../outside'])


def test_optional_record_failure_and_redaction(tmp_path,monkeypatch):
    log=tmp_path/'probe.log'
    assert capture_request(log,{'command':['echo','--password','private-value'], 'environment':{'CUSTOM':'private-env','PATH':'/bin'}})
    text=log.with_suffix('.summary.json').read_text()
    assert 'private-value' not in text and 'private-env' not in text
    import zog.image_build.trace_records as records
    monkeypatch.setattr(records,'write_json',lambda *a: (_ for _ in ()).throw(OSError('failed')))
    assert not capture_request(tmp_path/'other.log',{'command':['true']})


def test_adapter_reopens_interrupted_submission_without_duplicate(tmp_path):
    pytest.importorskip('box_control')
    from zog.box_control.errors import RuntimeOperationError
    from root_control.build import canonical_request
    from zog.image_build.box_control_adapter import BoxControlExecutionAdapter, BuildExecutionPending, BuildExecutionFailed
    class Control:
        def __init__(self): self.record=None; self.submissions=0; self.refreshes=0
        def refresh_build_job(self,job):
            self.refreshes += 1
            return self.record
        def register_build_root(self,**kw): pass
        def issue_build_request_id(self): return 'r1-123-'+'a'*32+'-'+'b'*64
        def inspect_build_job(self,job):
            if self.record is None: raise RuntimeOperationError('unknown build identity: job:'+job)
            return self.record
        def submit_build_job(self,request_id,**kw):
            self.submissions+=1
            self.record=dict(request_id=request_id,job_id=hashlib.sha256(request_id.encode()).hexdigest()[:32],
                request=canonical_request(kw),state='running',outcome=None,process_cleanup_complete=False,
                runtime_id='runtime',invocation_id='invocation',journal_reference='journal',boot_id='a'*32)
            raise OSError('submission response lost after owner accepted')
    control=Control()
    def adapter():
        return BoxControlExecutionAdapter(control,execution_user_id=1000,execution_group_id=1000,
            startup_timeout_seconds=30,termination_grace_seconds=5,wait_timeout_seconds=0,
            resource_limits={'thread-count-maximum':100,'memory-maximum-bytes':1000000},input_manifest_id='fixture')
    request=BuildExecutionRequest(tmp_path/'root',tmp_path/'source',tmp_path/'output',('true',),{'LANG':'C'},'/image-build/source',60)
    checkpoint=tmp_path/'build-0.controller.json'
    with pytest.raises(OSError): adapter().execute_for_attempt(request,checkpoint)
    saved=checkpoint.read_bytes()
    with pytest.raises(BuildExecutionPending): adapter().execute_for_attempt(request,checkpoint)
    assert control.submissions==1 and checkpoint.read_bytes()==saved
    assert control.refreshes == 1
    observed=json.loads((tmp_path/'build-0.observation.json').read_text())
    assert observed['state']=='running' and observed['boot_id']=='a'*32
    # Owner, not inspector, reconciles the different boot and records unknown.
    control.record.update(state='unknown',outcome='unknown',error='original outcome unknown')
    with pytest.raises(BuildExecutionPending): adapter().execute_for_attempt(request,checkpoint)
    observed=json.loads((tmp_path/'build-0.observation.json').read_text())
    assert observed['outcome']=='unknown' and control.submissions==1
    # Cancellation/cleanup can complete without recovering the original exit code.
    control.record.update(state='completed',process_cleanup_complete=True,outcome='cancelled',exit_code=None)
    with pytest.raises(BuildExecutionFailed): adapter().execute_for_attempt(request,checkpoint)
    observed=json.loads((tmp_path/'build-0.observation.json').read_text())
    assert observed['process_cleanup_complete'] and observed['outcome']=='cancelled'


def test_zero_wait_resume_observes_completion_without_resubmission(tmp_path, monkeypatch):
    pytest.importorskip('box_control')
    from zog.image_build.box_control_adapter import BoxControlExecutionAdapter
    from root_control.build import canonical_request
    from zog.box_control.errors import RuntimeOperationError
    class Control:
        record = None
        submissions = 0
        refreshes = 0
        def register_build_root(self, **kw): pass
        def issue_build_request_id(self): return 'r1-123-'+'c'*32+'-'+'d'*64
        def inspect_build_job(self, job):
            if self.record is None: raise RuntimeOperationError('unknown build identity: job:'+job)
            return dict(self.record)
        def submit_build_job(self, request_id, **kw):
            self.submissions += 1
            self.record = dict(request_id=request_id,job_id=hashlib.sha256(request_id.encode()).hexdigest()[:32],
                request=canonical_request(kw),state='running',outcome=None,process_cleanup_complete=False,
                runtime_id='runtime',invocation_id='invocation',journal_reference='journal')
            raise OSError('lost response')
        def refresh_build_job(self, job):
            self.refreshes += 1
            self.record.update(state='completed',outcome='success',exit_code=0,process_cleanup_complete=True)
            return dict(self.record)
    control = Control()
    adapter = BoxControlExecutionAdapter(control, execution_user_id=1000,execution_group_id=1000,
        startup_timeout_seconds=30,termination_grace_seconds=5,wait_timeout_seconds=0,
        resource_limits={'thread-count-maximum':100,'memory-maximum-bytes':1000000},input_manifest_id='fixture')
    request=BuildExecutionRequest(tmp_path/'root',tmp_path/'source',tmp_path/'output',('true',),{},'/image-build/source',60)
    checkpoint=tmp_path/'command.controller.json'
    with pytest.raises(OSError): adapter.execute_for_attempt(request,checkpoint)
    original=checkpoint.read_bytes()
    monkeypatch.setattr('zog.image_build.box_control_adapter.time.sleep',lambda _: pytest.fail('zero-wait slept'))
    result=adapter.execute_for_attempt(request,checkpoint)
    assert result.exit_code == 0 and result.cleanup_complete
    assert control.submissions == 1 and control.refreshes == 1
    assert checkpoint.read_bytes() == original
    adapter.execute_for_attempt(request,checkpoint)
    assert control.refreshes == 1
