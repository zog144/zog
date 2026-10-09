"""Optional inspection evidence. Never read by execution/recovery decisions."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from .filesystem import write_json

MAX_BYTES = 256 * 1024
ENVIRONMENT = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'DESTDIR', 'IMAGE_BUILD_SOURCE', 'IMAGE_BUILD_OUTPUT', 'CC', 'CXX', 'AR', 'LD', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'MAKEFLAGS', 'PKG_CONFIG_PATH', 'SOURCE_DATE_EPOCH'}
SECRET = re.compile(r'(?i)(password|passwd|token|secret|credential|authorization|cookie|private[-_]key|api[-_]key)')

def sanitize(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if SECRET.search(k) else sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        result, hide = [], False
        for item in value:
            result.append('[REDACTED]' if hide else sanitize(item))
            hide = isinstance(item, str) and item.startswith('-') and '=' not in item and bool(SECRET.search(item))
        return result
    if not isinstance(value, str):
        return value
    value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED]', value, flags=re.S)
    value = re.sub(r'\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16})\b', '[REDACTED]', value)
    value = re.sub(r'(?i)\bBearer\s+[^\s"\']+', 'Bearer [REDACTED]', value)
    value = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', value)
    value = re.sub(r'''(?ix)(?<![\w-])((?:[\w-]*(?:password|passwd|token|secret|credential|authorization|cookie|private[-_]key|api[-_]key)[\w-]*)\s*(?:=|:)\s*)("[^"\n]*"|'[^'\n]*'|[^\s;,]+)''', r'\1[REDACTED]', value)
    return re.sub(r'''(?ix)(--[\w-]*(?:password|passwd|token|secret|credential|api[-_]key)[\w-]*\s+)("[^"\n]*"|'[^'\n]*'|[^\s;]+)''', r'\1[REDACTED]', value)

def _write(path, record, *, immutable=False):
    # Caller already holds the execution/operation lock. No inspection failure
    # may turn a successful build into a failure or replace its original exception.
    try:
        record = sanitize(record)
        if len((json.dumps(record, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()) > MAX_BYTES:
            raise ValueError('inspection record exceeds budget')
        path = Path(path)
        if immutable and path.exists():
            return json.loads(path.read_text()) == record
        write_json(path, record)
        return True
    except Exception:
        logging.warning('Optional build inspection record unavailable')
        return False

def _component(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', value):
        raise ValueError('invalid trace identity')
    return value

def _relative(value):
    if not isinstance(value, str) or not value or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('invalid evidence reference')
    for part in value.split('/'):
        _component(part)
    return value

def capture_identity(log, *, attempt_id, command_id, package, stage_id, phase,
                     command_index, pipeline_id=None, provenance=None,
                     relationships=(), category='build', receipts=(), origin='captured'):
    """Capture once before submission; explicit relationships never imply acceptance.

    Diagnostic callers use this with category='diagnostic' and their own retained
    attempt/command IDs. Historical adapters use origin='imported' and exact receipts.
    Invalid metadata is rejected; automatic engine callers use safe_capture_identity.
    """
    _component(attempt_id); _relative(command_id)
    if Path(log).stem != command_id.split('/')[-1]:
        raise ValueError('command locator differs from log stem')
    if category not in ('build', 'diagnostic', 'retry') or origin not in ('captured', 'imported'):
        raise ValueError('invalid capture category/origin')
    if type(command_index) is not int or command_index < 0:
        raise ValueError('invalid command index')
    for value in (package, stage_id, phase):
        _component(value)
    if pipeline_id is not None: _component(pipeline_id)
    links = []
    for link in relationships:
        if set(link) != {'relation', 'target'} or link['relation'] not in ('retry-of', 'diagnostic-of'):
            raise ValueError('invalid relationship')
        target = link['target']
        if set(target) not in ({'job_id'}, {'attempt_id', 'command_id'}):
            raise ValueError('relationship requires exact job or command identity')
        for key, value in target.items():
            (_relative if key == 'command_id' else _component)(value)
        if target == {'attempt_id': attempt_id, 'command_id': command_id}:
            raise ValueError('self relationship')
        links.append(link)
    if len(links) > 32 or len(receipts) > 32: raise ValueError('too many references')
    for ref in receipts: _relative(ref)
    return _write(Path(log).with_suffix('.trace.json'), dict(schema=1, attempt_id=attempt_id,
        command_id=command_id, package=package, stage_id=stage_id, phase=phase,
        command_index=command_index, pipeline_id=pipeline_id, category=category, origin=origin,
        title=f'{package} · {phase} {command_index} · {stage_id} · {attempt_id}',
        provenance=provenance or {}, relationships=links, receipts=list(receipts)), immutable=True)

def safe_capture_identity(*args, **kwargs):
    try:
        return capture_identity(*args, **kwargs)
    except Exception:
        logging.warning('Optional build inspection identity unavailable')
        return False

def capture_request(log, request, policy=None, *, origin='captured', request_id=None):
    raw = asdict(request) if not isinstance(request, dict) else request
    request = {k: raw[k] for k in ('command', 'working_directory', 'timeout_seconds', 'read_only_root', 'network_access') if k in raw}
    request['environment'] = {k: v if k in ENVIRONMENT else '[REDACTED]' for k, v in raw.get('environment', {}).items()}
    return _write(Path(log).with_suffix('.summary.json'), dict(schema=1, origin=origin,
                  request=request, policy=policy, request_id=request_id), immutable=True)

def capture_observation(checkpoint, record, *, origin='captured'):
    fields = ('request_id', 'job_id', 'state', 'outcome', 'exit_code', 'signal', 'error',
              'runtime_id', 'invocation_id', 'boot_id', 'unit_name', 'journal_reference',
              'process_cleanup_complete', 'resources_released', 'cancel_requested', 'completed_at')
    path = Path(checkpoint)
    stem = path.name.removesuffix('.controller.json')
    return _write(path.with_name(stem + '.observation.json'), dict(schema=1, origin=origin,
        observed_at=datetime.now(timezone.utc).isoformat(), **{k: record[k] for k in fields if k in record}))

def import_diagnostic(log, *, attempt_id, command_id, package, stage_id, phase,
                      command_index, controller_record, receipts, relationships=(),
                      provenance=None, category='diagnostic'):
    """Explicit historical adoption of an owner-verified controller record.

    The caller supplies exact receipt references relative to state/image-build;
    this function neither searches receipts nor fabricates execution checkpoints.
    Run under the attempt owner's lock. No submission, refresh or acceptance occurs.
    """
    request_id = controller_record.get('request_id')
    if not isinstance(request_id, str) or not re.fullmatch(r'r1-[0-9a-f]+-[0-9a-f]{32}-[0-9a-f]{64}', request_id):
        raise ValueError('invalid controller request identity')
    if controller_record.get('job_id') != hashlib.sha256(request_id.encode()).hexdigest()[:32]:
        raise ValueError('controller job binding differs')
    request = controller_record['request']
    if not isinstance(request.get('command'), list) or not request['command'] or not all(isinstance(v, str) for v in request['command']):
        raise ValueError('invalid controller argv')
    if not receipts: raise ValueError('historical import requires exact evidence references')
    if not capture_identity(log, attempt_id=attempt_id, command_id=command_id,
        package=package, stage_id=stage_id, phase=phase, command_index=command_index,
        provenance=provenance, relationships=relationships, category=category,
        receipts=receipts, origin='imported'):
        return False
    if not capture_request(log, request, origin='imported', request_id=request_id): return False
    return capture_observation(Path(log).with_suffix('.controller.json'), controller_record, origin='imported')
