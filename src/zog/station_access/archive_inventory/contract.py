"""Strict allowlisted observation schema; arbitrary provenance and URLs are forbidden."""
import re
import uuid
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime

MAX_ITEMS = 10000
PAGE_SIZE = 100
MAX_BODY = 256000
MAX_AGE = 300


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError('Invalid fields')


def integer(value, maximum=2**53-1, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid number')


def text(value, pattern, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('Invalid text')


def validate(value):
    exact(value, 'version host_id role_revision observation_id observed_at status serving lease_expires_at summary total offset items preparation')
    if type(value['version']) is not int or value['version'] not in (1, 2):
        raise ValueError('Unsupported version')
    uuid.UUID(value['host_id']); uuid.UUID(value['observation_id'])
    integer(value['role_revision']); integer(value['total'], MAX_ITEMS); integer(value['offset'], MAX_ITEMS)
    at = parse_datetime(value['observed_at'])
    if not at or timezone.is_naive(at) or not timezone.now()-timedelta(seconds=MAX_AGE) <= at <= timezone.now()+timedelta(seconds=5):
        raise ValueError('Observation expired')
    if value['status'] not in {'ok', 'unavailable', 'limit-exceeded'} or type(value['serving']) is not bool:
        raise ValueError('Invalid status')
    integer(value['lease_expires_at'], nullable=True)
    if value['serving'] and (value['status'] != 'ok' or not value['lease_expires_at'] or not at.timestamp() < value['lease_expires_at'] <= at.timestamp()+905):
        raise ValueError('Missing lease')
    exact(value['preparation'], 'state attempt_id')
    if value['preparation']['state'] not in {'unknown', 'preparing', 'ready', 'failed', 'uncertain', 'deleting', 'deleted'}:
        raise ValueError('Invalid preparation state')
    text(value['preparation']['attempt_id'], r'[0-9a-f]{32}', nullable=True)
    if value['preparation']['state'] != 'unknown' and value['preparation']['attempt_id'] is None:
        raise ValueError('Missing preparation evidence')
    summary = value['summary']
    exact(summary, 'collections logical_bytes unique_content_bytes allocated_object_bytes accounting_complete filesystems')
    if not isinstance(summary['collections'], list) or len(summary['collections']) > 100 or len(set(summary['collections'])) != len(summary['collections']):
        raise ValueError('Invalid collections')
    for name in summary['collections']:
        text(name, r'[a-z0-9][a-z0-9_-]{0,63}')
    for field in ['logical_bytes', 'unique_content_bytes', 'allocated_object_bytes']:
        integer(summary[field], nullable=True)
    if type(summary['accounting_complete']) is not bool:
        raise ValueError('Invalid accounting')
    if not isinstance(summary['filesystems'], list) or len(summary['filesystems']) > 16:
        raise ValueError('Too many filesystems')
    devices = set()
    for fs in summary['filesystems']:
        exact(fs, 'id stores total_bytes used_bytes available_bytes allocated_object_bytes')
        text(fs['id'], r'[0-9]{1,20}')
        if fs['id'] in devices:
            raise ValueError('Duplicate filesystem')
        devices.add(fs['id'])
        if not isinstance(fs['stores'], list) or not fs['stores'] or len(fs['stores']) > 3 or any(x not in {'store', 'objects', 'object'} for x in fs['stores']):
            raise ValueError('Invalid filesystem scopes')
        for field in ['total_bytes', 'used_bytes', 'available_bytes', 'allocated_object_bytes']:
            integer(fs[field], nullable=True)
    if not isinstance(value['items'], list) or len(value['items']) > PAGE_SIZE or value['offset']+len(value['items']) > value['total']:
        raise ValueError('Invalid page')
    if value['total'] and not value['items']:
        raise ValueError('Empty continuation')
    if value['status'] != 'ok' and (value['total'] or value['serving']):
        raise ValueError('Invalid failed observation')
    for row in value['items']:
        exact(row, 'collection digest kind name version size_bytes availability filesystem_id provenance approval' + (' licenses' if value['version'] == 2 else ''))
        if value['version'] == 2:
            from zog.archive_mirror.notice_contract import validate_summary
            validate_summary(row['licenses'])
        text(row['collection'], r'[a-z0-9][a-z0-9_-]{0,63}')
        if row['collection'] not in summary['collections']:
            raise ValueError('Unlisted collection')
        text(row['digest'], r'[0-9a-f]{64}')
        text(row['name'], r'[A-Za-z0-9][A-Za-z0-9._+ -]{0,199}', nullable=True)
        text(row['version'], r'[0-9a-f]{7,64}', nullable=True)
        integer(row['size_bytes'], nullable=True)
        if row['kind'] not in {'source', 'root-filesystem'} or row['availability'] not in {'present', 'missing', 'size-mismatch', 'unknown'}:
            raise ValueError('Invalid item')
        if row['provenance'] not in {'source-export', 'local-import', 'unknown'} or row['approval'] not in {'approved', 'unapproved', 'unknown'}:
            raise ValueError('Invalid provenance')
        if row['filesystem_id'] is not None and row['filesystem_id'] not in devices:
            raise ValueError('Unknown filesystem')
    return at
