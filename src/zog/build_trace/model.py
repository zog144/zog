"""Versioned values, bounded output and conservative presentation redaction."""
import base64
import hashlib
import json
import re

SCHEMA = 1
MAX_RESPONSE = 1024 * 1024

class TraceError(Exception):
    def __init__(self, code, message, *, details=None):
        self.code = code
        self.details = details
        super().__init__(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def fact(value=None, source=None, *, origin='captured', reason='not-recorded'):
    if value is None:
        return dict(value=None, origin='missing', source=source, reason=reason)
    return dict(value=value, origin=origin, source=source)


SECRET = re.compile(r'(?i)(password|passwd|token|secret|credential|authorization|cookie|private[-_]key|api[-_]key)')
ASSIGNMENT = re.compile(r'''(?ix)(?<![\w-])((?:[\w-]*(?:password|passwd|token|secret|credential|authorization|cookie|private[-_]key|api[-_]key)[\w-]*)\s*(?:=|:)\s*)("[^"\n]*"|'[^'\n]*'|[^\s;,]+)''')
FLAG = re.compile(r'''(?ix)(--[\w-]*(?:password|passwd|token|secret|credential|api[-_]key)[\w-]*\s+)("[^"\n]*"|'[^'\n]*'|[^\s;]+)''')
ENVIRONMENT = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'DESTDIR', 'IMAGE_BUILD_SOURCE', 'IMAGE_BUILD_OUTPUT', 'CC', 'CXX', 'AR', 'LD', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'MAKEFLAGS', 'PKG_CONFIG_PATH', 'SOURCE_DATE_EPOCH'}


def redact_text(value):
    value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED]', value, flags=re.S)
    value = re.sub(r'\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16})\b', '[REDACTED]', value)
    value = re.sub(r'(?i)\bBearer\s+[^\s"\']+', 'Bearer [REDACTED]', value)
    value = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', value)
    return FLAG.sub(r'\1[REDACTED]', ASSIGNMENT.sub(r'\1[REDACTED]', value))


def redact(value):
    if isinstance(value, dict):
        return {k: ({'value': None, 'origin': 'redacted', 'reason': 'sensitive-field'} if SECRET.search(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        result, hide_next = [], False
        for item in value:
            result.append('[REDACTED]' if hide_next else redact(item))
            hide_next = isinstance(item, str) and item.startswith('-') and '=' not in item and bool(SECRET.search(item))
        return result
    return redact_text(value) if isinstance(value, str) else value


def environment(values, source):
    if values is None:
        return fact(source=source)
    return fact({key: {'value': redact(value), 'origin': 'captured'} if key in ENVIRONMENT else
                 {'value': None, 'origin': 'redacted', 'reason': 'environment-not-allowlisted'}
                 for key, value in values.items()}, source)


def response(kind, **values):
    raw = dict(schema_version=SCHEMA, kind=kind, **values)
    if len(encoded(raw)) > MAX_RESPONSE:
        raise TraceError('response-too-large', 'Response exceeds 1 MiB; use a smaller page or narrower query.')
    result = redact(raw)
    if len(encoded(result)) > MAX_RESPONSE:
        raise TraceError('response-too-large', 'Response exceeds 1 MiB; use a smaller page or narrower query.')
    return result


def limit_value(limit):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise TraceError('invalid-query', 'limit must be an integer from 1 through 100')


def paginate(rows, *, scope, cursor=None, limit=50, key=lambda r: r['id']):
    limit_value(limit)
    after = read_cursor(cursor, scope)
    selected = sorted((r for r in rows if after is None or key(r) > after), key=key)
    page = selected[:limit]
    more = len(selected) > limit
    next_cursor = make_cursor(key(page[-1]), scope) if more else None
    return dict(items=page, has_more=more, next_cursor=next_cursor)


def read_cursor(cursor, scope):
    after = None
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError()
            saved = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
            if saved['scope'] != digest(scope) or not isinstance(saved['after'], str):
                raise ValueError()
            after = saved['after']
        except (ValueError, KeyError, TypeError):
            raise TraceError('invalid-cursor', 'Cursor is invalid or belongs to another query.') from None
    return after


def make_cursor(after, scope):
    return base64.urlsafe_b64encode(encoded({"scope": digest(scope), "after": after})).decode()
