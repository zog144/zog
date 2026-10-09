"""Version-1 owner inspection records and bounded failure/evidence projections."""
import hashlib
import re
from .model import TraceError, fact, redact
from .source import component

EXTRA_SUFFIXES = ('.trace.json', '.summary.json', '.observation.json')

def read_records(snap, path, attempt, command_id, view, *, metadata_only=False):
    trace = snap.read(path + '.trace.json')
    summary, observation = (None, None) if metadata_only else (snap.read(path + suffix) for suffix in EXTRA_SUFFIXES[1:])
    for raw in (trace, summary, observation):
        if raw is not None and (raw.get('schema') != 1 or raw.get('origin') not in ('captured', 'imported')):
            raise TraceError('unsupported-schema', 'Unsupported owner inspection record.')
    if trace is not None:
        if trace.get('attempt_id') != attempt or trace.get('command_id') != command_id:
            raise TraceError('integrity-error', 'Trace identity differs from command locator.')
        if type(trace.get('command_index')) is not int or trace['command_index'] < 0:
            raise TraceError('invalid-record', 'Invalid trace command index.')
        for key in ('package', 'stage_id', 'phase'):
            component(trace[key])
        if trace.get('pipeline_id') is not None: component(trace['pipeline_id'])
        if trace.get('category') not in ('build', 'diagnostic', 'retry') or not isinstance(trace.get('title'), str):
            raise TraceError('invalid-record', 'Invalid trace description.')
        if view:
            for key in ('attempt_id', 'package', 'stage_id', 'phase', 'command_index', 'pipeline_id'):
                if trace.get(key) != view.get(key):
                    raise TraceError('integrity-error', 'Trace identity differs from command view.')
        links, receipts = trace.get('relationships'), trace.get('receipts')
        if not isinstance(links, list) or not isinstance(receipts, list) or len(links) > 32 or len(receipts) > 32:
            raise TraceError('invalid-record', 'Invalid trace references.')
        for link in links:
            if set(link) != {'relation', 'target'} or link['relation'] not in ('retry-of', 'diagnostic-of'):
                raise TraceError('invalid-record', 'Invalid explicit relationship.')
            target = link['target']
            if set(target) not in ({'job_id'}, {'attempt_id', 'command_id'}):
                raise TraceError('invalid-record', 'Relationship requires exact target identity.')
            for key, value in target.items():
                for part in value.split('/') if key == 'command_id' else [value]: component(part)
            if target == {'attempt_id': attempt, 'command_id': command_id}:
                raise TraceError('integrity-error', 'Self relationship is invalid.')
        for ref in receipts:
            for part in ref.split('/'): component(part)
    if summary is not None and not isinstance(summary.get('request'), dict):
        raise TraceError('invalid-record', 'Invalid request summary.')
    if observation is not None:
        for key in ('process_cleanup_complete', 'resources_released', 'cancel_requested'):
            if key in observation and type(observation[key]) is not bool:
                raise TraceError('invalid-record', 'Invalid observed cleanup state.')
        for key in ('exit_code', 'signal'):
            if observation.get(key) is not None and type(observation[key]) is not int:
                raise TraceError('invalid-record', 'Invalid observed result.')
    return trace, summary, observation

def job_identity(request_id, job_id=None):
    if not isinstance(request_id, str) or not re.fullmatch(r'r1-[0-9a-f]+-[0-9a-f]{32}-[0-9a-f]{64}', request_id):
        raise TraceError('invalid-record', 'Request identity is invalid.')
    expected = hashlib.sha256(request_id.encode()).hexdigest()[:32]
    if job_id is not None and job_id != expected:
        raise TraceError('integrity-error', 'Job identity differs from request identity.')
    return expected

def recovery(record, execution, source, resource_source=None):
    record = record or {}
    cleanup = record.get('process_cleanup_complete', (execution or {}).get('cleanup_complete'))
    released = record.get('resources_released')
    outcome, state = record.get('outcome'), record.get('state')
    if cleanup is True:
        status, reason = 'complete', 'process-cleanup-confirmed; resource-release-is-separate'
    elif outcome == 'unknown' or state == 'unknown':
        status, reason = 'blocked', 'owner-reconciliation-required; original-outcome-unknown'
    elif cleanup is False:
        status, reason = 'pending', 'owner-process-cleanup-not-complete'
    else:
        status, reason = 'unknown', 'no-owner-cleanup-observation'
    return dict(status=status, reason=reason, owner='box-control', automatic_action=False,
                process_cleanup_complete=fact(cleanup, source), resources_released=fact(released, resource_source or source))

def evidence(path, view, checkpoint, execution, trace, summary, observation, job_id, journal):
    rows = [dict(kind=kind, reference=path+suffix, availability='available' if raw is not None else 'missing')
            for kind, suffix, raw in [('identity-view','.view.json',view), ('inspection-identity','.trace.json',trace),
                ('request-summary','.summary.json',summary), ('submission-binding','.controller.json',checkpoint),
                ('completion','.execution.json',execution), ('controller-observation','.observation.json',observation)]]
    if job_id: rows.append(dict(kind='controller-job', reference='box-control:job:'+job_id, availability='not-checked'))
    if journal is not None: rows.append(dict(kind='journal', reference=journal, availability='not-checked'))
    for ref in (trace or {}).get('receipts', []):
        rows.append(dict(kind='owner-receipt', reference=ref, availability='not-checked'))
    return rows

def failure(command, owner_error=None):
    outcome = command['outcome']['value']
    failed = outcome not in (None, 'unknown', 'success') or command['exit_code']['value'] not in (None, 0)
    return dict(status='failed' if failed else ('unknown' if outcome in (None, 'unknown') else 'none'),
        package=command['package'], phase=command['phase'], command_id=command['id'],
        submission='established' if command['observation_source'] is not None or command['completion_available'] else
                   ('prepared-only' if command['job_id']['value'] else 'not-established'),
        execution='established' if command['execution']['invocation_id']['value'] is not None else 'not-established',
        outcome=command['outcome'], exit_code=command['exit_code'], signal=command['execution']['signal'],
        owner_error=fact(redact(owner_error)[:2048] if isinstance(owner_error, str) else None, command['observation_source']),
        owner_error_truncated=isinstance(owner_error, str) and len(redact(owner_error)) > 2048, recovery=command['recovery'])
