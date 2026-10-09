"""Translation of the pass11 per-invocation journal API into portal log pages."""
from datetime import datetime, timezone
import hashlib
import json
from .logs import LogEntry, LogPage, LogsUnavailable, LogCursorExpired


def project_page(raw, *, program, invocation_id, cursor, scope):
    status = raw.get('status')
    if status == 'cursor-unavailable':
        raise LogCursorExpired('Journal history changed and the saved position is gone. Reload recent entries to start a new tail.')
    if status == 'identity-unavailable':
        raise LogsUnavailable('No recorded execution identity is available for this log stream.')
    if status == 'unavailable':
        raise LogsUnavailable(raw.get('error') or 'The journal reader is temporarily unavailable. Retry without changing the log position.')
    if status not in ('ok', 'empty-history'):
        raise LogsUnavailable('Unknown journal response status')
    entries = []
    for index, item in enumerate(raw['entries']):
        microseconds = item.get('timestamp_microseconds')
        try:
            timestamp = datetime.fromtimestamp(int(microseconds) / 1_000_000, timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            timestamp = 'Timestamp unavailable'
        try:
            priority = int(item.get('priority'))
        except (TypeError, ValueError):
            priority = 6
        priority = priority if 0 <= priority <= 7 else 6
        unavailable = bool(item.get('message_unavailable'))
        message = '[Message unavailable in this bounded journal response]' if unavailable else item.get('message', '')
        if not isinstance(message, str):
            raise LogsUnavailable('Journal returned an invalid message')
        # pass11 exposes only a page cursor, not individual journal cursors. Use a
        # stable page/position key; never deduplicate separate identical messages.
        identity = hashlib.sha256(json.dumps([scope, cursor, raw.get('next_cursor'), index], sort_keys=True).encode()).hexdigest()
        entries.append(LogEntry(identity, timestamp, program, priority, message, invocation_id))
    return LogPage(tuple(entries), raw.get('next_cursor'), bool(raw.get('has_more')), 'journald', status)


class JournalReader:
    def __init__(self, control):
        self.control = control

    def read_logs(self, runtime_id, *, program=None, cursor=None, limit=50):
        from zog.box_control.errors import RuntimeOperationError
        reference = self.control.application_runtime(runtime_id)
        if reference is None:
            raise LogsUnavailable('Runtime history is no longer available')
        if program is None:
            if len(reference.programs) != 1:
                raise LogsUnavailable('Select one program to view its journal stream')
            program = reference.programs[0].program
        member = next((p for p in reference.programs if p.program == program), None)
        if member is None:
            raise LogsUnavailable('Program does not belong to this runtime')
        try:
            raw = self.control.application_logs(runtime_id, program, cursor=cursor, limit=limit)
        except (RuntimeOperationError, ValueError) as exc:
            raise LogsUnavailable(str(exc)) from exc
        return project_page(raw, program=program, invocation_id=member.invocation_id,
            cursor=cursor, scope=[runtime_id, program, reference.boot_id, member.invocation_id])

    def read_build_logs(self, job_id, *, cursor=None, limit=50):
        from zog.box_control.errors import RuntimeOperationError
        try:
            record = self.control.inspect_build_job(job_id)
            raw = self.control.build_job_logs(job_id, cursor=cursor, limit=limit)
        except (RuntimeOperationError, ValueError) as exc:
            raise LogsUnavailable(str(exc)) from exc
        return project_page(raw, program='build-command', invocation_id=record.get('invocation_id'),
            cursor=cursor, scope=['build-job', job_id, record.get('boot_id'), record.get('invocation_id')])


def create_reader(control):
    return JournalReader(control)
