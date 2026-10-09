"""Resumable synchronous projection of the controller's richer build records."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import uuid

from .errors import ImageBuildError
from .runner import BuildExecutionResult


class BuildExecutionPending(ImageBuildError):
    def __init__(self, record):
        self.request_id = record['request_id']
        self.job_id = record['job_id']
        self.state = record['state']
        for name in ('build_root_id','source_workspace_id','output_workspace_id'):
            setattr(self, name, record['request'][name])
        super().__init__(f'build {self.job_id} is {self.state}; resume the same command checkpoint')


class BuildRegistrationPending(ImageBuildError):
    """A sent registration needs later inspection, never a replacement request."""
    def __init__(self, resource_id, observed):
        self.resource_id = resource_id
        self.state = observed['state']
        self.phase = observed.get('phase')
        super().__init__(f'registration {resource_id} is {self.state}; revisit the same identity')


class BuildExecutionFailed(ImageBuildError):
    def __init__(self, record):
        self.record = record
        super().__init__(f"build {record['job_id']}: {record['outcome']}; {record.get('error') or record.get('journal_reference')}")


class BoxControlExecutionAdapter:
    def __init__(self, control, *, execution_user_id, execution_group_id,
                 startup_timeout_seconds, termination_grace_seconds, wait_timeout_seconds,
                 resource_limits, input_manifest_id, device_profile=None):
        self.device_profile = device_profile
        self.control = control
        self.execution_user_id = execution_user_id
        self.execution_group_id = execution_group_id
        self.startup_timeout_seconds = startup_timeout_seconds
        self.termination_grace_seconds = termination_grace_seconds
        self.wait_timeout_seconds = wait_timeout_seconds
        self.resource_limits = dict(resource_limits)
        # Explicit value or caller resolver; never infer this from an arbitrary path.
        self.input_manifest_id = input_manifest_id
        if wait_timeout_seconds < 0: raise ValueError('negative caller wait timeout')

    def configuration(self):
        return dict(**({'device_profile':self.device_profile} if self.device_profile is not None else {}), project_root=str(self.control.project.path),
                    socket_path=str(getattr(self.control.systemd_transport, "socket_path", "test-transport")),
                    execution_user_id=self.execution_user_id,
                    execution_group_id=self.execution_group_id,
                    startup_timeout_seconds=self.startup_timeout_seconds,
                    termination_grace_seconds=self.termination_grace_seconds,
                    resource_limits=self.resource_limits)

    def release_resources(self, directory):
        from zog.box_control.build_jobs import BuildJobs
        from zog.box_control.durability import replace_json
        directory = Path(directory)
        resource_path = directory / 'controller-resources.json'
        if not resource_path.exists(): return
        released = directory / 'controller-released.json'
        if released.exists(): return
        resource = json.loads(resource_path.read_text())
        for checkpoint in sorted(directory.glob('*.controller.json')):
            saved = json.loads(checkpoint.read_text())
            if saved['resource_id'] != resource['resource_id']:
                raise ImageBuildError('command resource identity differs')
            job_id = BuildJobs.job_id(saved['request_id'])
            record = self.control.refresh_build_job(job_id)
            if not record['process_cleanup_complete']:
                raise BuildExecutionPending(record)
            released_record = self.control.release_build_job(job_id)
            if isinstance(released_record, dict):
                from .trace_records import capture_observation
                capture_observation(checkpoint, released_record)
        self.control.release_build_root(resource['resource_id'])
        replace_json(released, {'resource_id': resource['resource_id']})

    def _register(self, resource_id, registration, directory):
        """Reconcile only a typed registration reply timeout; never retry starts."""
        from zog.box_control.durability import replace_json
        from zog.box_control import errors
        pending_path = directory/'registration-pending.json'
        binding = {'resource_id': resource_id, 'registration': registration}

        def inspect():
            observed = self.control.inspect_build_root(resource_id)
            replace_json(directory/'registration-progress.json', {
                'resource_id': resource_id, 'state': observed['state'],
                'phase': observed.get('phase'), 'updated_at': observed.get('updated_at')})
            if observed['state'] not in {'ready', 'importing', 'absent'}:
                raise ImageBuildError('Registration cannot continue: '+observed['state'])
            return observed

        def reconcile_ready():
            result = self.control.register_build_root(resource_id=resource_id, **registration)
            # Only the controller reconciles its mutation guard. A crash before
            # removing this marker simply repeats the safe ready inspection.
            pending_path.unlink()
            from .filesystem import sync_directory
            sync_directory(directory)
            return result

        if pending_path.exists():
            if json.loads(pending_path.read_text()) != binding:
                raise ImageBuildError('Pending registration identity or intent changed')
            observed = inspect()
            if observed['state'] != 'ready':
                raise BuildRegistrationPending(resource_id, observed)
            return reconcile_ready()
        try:
            return self.control.register_build_root(resource_id=resource_id, **registration)
        except errors.RecoveryRequired as failure:
            cause = failure
            timeout_type = getattr(errors, 'RootControlReplyTimeout', ())
            while cause is not None and not isinstance(cause, timeout_type):
                cause = cause.__cause__
            if cause is None or cause.operation != 'build_register':
                raise
            replace_json(pending_path, binding)
            observed = {'state': 'absent'}
            # Bound both caller time and poll count. Inspection calls are independently
            # bounded by box-control (10s). An old controller fails closed here.
            deadline = time.monotonic() + 120
            for delay in (1, 2, 4, 8, 15, 15, 15, 15):
                if time.monotonic() + delay >= deadline:
                    break
                time.sleep(delay)
                observed = inspect()
                print(f"Registration {resource_id}: {observed['state']} / {observed.get('phase', 'unknown')}", flush=True)
                if observed['state'] == 'ready':
                    # The mutation API validates identical intent and clears its own
                    # recovery marker. No caller edits controller state.
                    return reconcile_ready()
            raise BuildRegistrationPending(resource_id, observed) from failure

    def execute_for_attempt(self, request, checkpoint):
        from zog.box_control.durability import replace_json
        from zog.box_control.locking import ProjectLock
        from .trace_records import capture_request, capture_observation
        checkpoint = Path(checkpoint)
        with ProjectLock(checkpoint.with_suffix('.lock')):
            intent = json.loads(json.dumps(asdict(request),default=str,allow_nan=False))
            manifest_id = self.input_manifest_id(request) if callable(self.input_manifest_id) else self.input_manifest_id
            config = dict(execution_user_id=self.execution_user_id, execution_group_id=self.execution_group_id,
                          startup_timeout_seconds=self.startup_timeout_seconds, termination_grace_seconds=self.termination_grace_seconds,
                          resource_limits=self.resource_limits, input_manifest_id=manifest_id)
            if self.device_profile is not None: config['device_profile'] = self.device_profile
            binding = {'request':intent,'configuration':config}
            capture_request(checkpoint.with_name(checkpoint.name.removesuffix('.controller.json') + '.log'), request, config)
            # One shared registration across this package's sequential commands.
            resources_path = request.root.parent / 'controller-resources.json'
            with ProjectLock(resources_path.with_suffix('.lock')):
                registration = dict(prepared_root=str(request.root),source_directory=str(request.source),
                                    output_directory=str(request.output),input_manifest_id=manifest_id,
                                    execution_user_id=self.execution_user_id,execution_group_id=self.execution_group_id)
                if resources_path.exists():
                    resource = json.loads(resources_path.read_text())
                    if resource['registration'] != registration: raise ImageBuildError('package resource binding changed')
                else:
                    resource = {'resource_id':uuid.uuid4().hex,'registration':registration}
                    replace_json(resources_path,resource)
                if not checkpoint.exists():
                    self._register(resource['resource_id'], registration, request.root.parent)
            rid = resource['resource_id']
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text())
                if saved['binding'] != binding or saved['resource_id'] != rid:
                    raise ImageBuildError('command attempt intent changed; cannot reuse identity')
            else:
                request_id = self.control.issue_build_request_id()
                from zog.box_control.build_jobs import BuildJobs
                saved = dict(binding=binding,resource_id=rid,request_id=request_id,job_id=BuildJobs.job_id(request_id))
                replace_json(checkpoint,saved)  # Durable before first submission.
            arguments = dict(build_root_id=rid,source_workspace_id=rid+'-source',output_workspace_id=rid+'-output',
                command=list(request.command),environment=dict(request.environment),working_directory=request.working_directory,
                read_only_root=request.read_only_root,network_access=request.network_access,
                execution_timeout_seconds=request.timeout_seconds,
                **{k:v for k,v in config.items() if k != 'input_manifest_id'})
            from zog.box_control.build_jobs import BuildJobs
            from zog.box_control.errors import RuntimeOperationError
            from zog.box_control.build_protocol import canonical_request
            job_id = BuildJobs.job_id(saved['request_id'])
            try:
                record = self.control.inspect_build_job(job_id)
            except RuntimeOperationError as error:
                # Absence of the controller's authoritative record proves that
                # this identity has not been accepted. Other read faults block.
                if str(error) != 'unknown build identity: job:' + job_id:
                    raise
                record = self.control.submit_build_job(request_id=saved['request_id'], **arguments)
            if record['request_id'] != saved['request_id'] or record['request'] != canonical_request(arguments):
                raise ImageBuildError('controller record differs from command binding')
            # Nonblocking resume must reconcile once before checking its deadline.
            # inspect_build_job only reads persisted state, which may be stale.
            if not record['process_cleanup_complete']:
                record = self.control.refresh_build_job(record['job_id'])
            capture_observation(checkpoint, record)
            deadline = time.monotonic()+self.wait_timeout_seconds
            while not record['process_cleanup_complete']:
                if record['state']=='unknown' or time.monotonic() >= deadline:
                    raise BuildExecutionPending(record)
                time.sleep(min(0.2,max(0,deadline-time.monotonic())))
                record = self.control.refresh_build_job(record['job_id'])
                capture_observation(checkpoint, record)
            if record['outcome'] not in ('success','nonzero-exit'):
                raise BuildExecutionFailed(record)
            if record['exit_code'] is None or not record['invocation_id'] or not record['journal_reference']:
                raise BuildExecutionFailed(record)
            return BuildExecutionResult(record['runtime_id'],record['invocation_id'],record['exit_code'],
                                        record['process_cleanup_complete'],record['journal_reference'])
