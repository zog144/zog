"""Station-access projection; the pass11 box-control API is adapted here.

Cursors are opaque and belong to one runtime/program filter. Implementations must
scope journald reads by recorded invocation IDs, not by reusable unit names alone.
"""
from dataclasses import dataclass

class LogsUnavailable(RuntimeError):
    pass

class LogCursorExpired(ValueError):
    pass

@dataclass(frozen=True)
class LogEntry:
    cursor: str
    timestamp: str
    program: str
    priority: int
    message: str
    invocation_id: str | None = None

@dataclass(frozen=True)
class LogPage:
    entries: tuple[LogEntry, ...]
    next_cursor: str | None
    has_more: bool = False
    source: str = 'journald'
    status: str = 'ok'


def validate_page(page, runtime, limit):
    if not isinstance(page, LogPage) or len(page.entries) > limit:
        raise LogsUnavailable('log adapter returned an invalid page')
    if page.next_cursor is not None and (not isinstance(page.next_cursor, str) or len(page.next_cursor) > 4096):
        raise LogsUnavailable('log adapter returned an invalid cursor')
    if page.source not in ('journald', 'fixture'):
        raise LogsUnavailable('log adapter returned an invalid source')
    programs = {p.name: p for p in runtime.programs}
    for entry in page.entries:
        program = programs.get(entry.program)
        if (program is None or not isinstance(entry.cursor, str) or len(entry.cursor) > 4096
            or not isinstance(entry.message, str) or len(entry.message) > 262144
            or type(entry.priority) is not int or not 0 <= entry.priority <= 7
            or (page.source == 'journald' and (not program.invocation_id or entry.invocation_id != program.invocation_id))):
            raise LogsUnavailable('log adapter returned entries outside the recorded runtime or size bounds')
    return page
