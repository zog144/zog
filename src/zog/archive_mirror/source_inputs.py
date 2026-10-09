"""Populate exact reviewed image-build source bytes into the sources collection."""
import datetime
import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from django.db import transaction
from .config import configuration
from .models import Archive, ReviewedSource, SourcePinSet
from .store import open_object, publish

IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,179}')
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+:-]{0,199}')
DIGEST = re.compile(r'[0-9a-f]{64}')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _text(value, name, optional=False):
    if optional and value in (None, ''):
        return ''
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise ValueError('Invalid reviewed source ' + name)
    return value

def _url(value):
    if not isinstance(value, str):
        raise ValueError('Canonical URL required')
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Credential-free HTTPS canonical URL required')
    if parts.fragment or parts.query:
        raise ValueError('Canonical URL query/fragment unsupported')
    return value

def decode_manifest(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) > 8 * 1024 * 1024:
        raise ValueError('Invalid reviewed source manifest')
    try:
        value = json.loads(bytes(data))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Invalid reviewed source manifest')
    if not isinstance(value, dict) or set(value) != {'schema','pin_set','date','sources'} or value['schema'] != 1:
        raise ValueError('Unsupported reviewed source manifest')
    identity = value['pin_set']
    if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
        raise ValueError('Invalid pin-set identity')
    try:
        pin_date = datetime.date.fromisoformat(value['date'])
    except (TypeError, ValueError):
        raise ValueError('Invalid pin-set date')
    if not isinstance(value['sources'], list) or not value['sources'] or len(value['sources']) > 10000:
        raise ValueError('Reviewed sources required')
    sources = []
    declarations = set()
    for item in value['sources']:
        if not isinstance(item, dict) or not {'url','sha256'} <= set(item) or set(item) - {'url','sha256','package','source'}:
            raise ValueError('Invalid reviewed source declaration')
        digest = item['sha256']
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError('Invalid reviewed source digest')
        record = {
            'url': _url(item['url']),
            'sha256': digest,
            'package': _text(item.get('package'), 'package', True),
            'source': _text(item.get('source'), 'source', True),
        }
        key = tuple(record[k] for k in ('url','sha256','package','source'))
        if key in declarations:
            raise ValueError('Duplicate reviewed source declaration')
        declarations.add(key); sources.append(record)
    return identity, pin_date, sources

def _existing(digest):
    archive = Archive.objects.filter(collection='sources', digest=digest).first()
    if not archive:
        return None
    with open_object(digest) as stream:
        if stream.seek(0, 2) != archive.size:
            raise ValueError('Stored reviewed source size mismatch')
        stream.seek(0)
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            raise ValueError('Stored reviewed source corrupt')
    return archive

def _download(record, opener=None):
    opener = opener or urllib.request.build_opener(NoRedirect())
    maximum = configuration().get('maximum_archive_bytes', 16 * 1024**3)
    temporary = tempfile.NamedTemporaryFile(prefix='archive-source-', delete=False)
    path = Path(temporary.name)
    checksum = hashlib.sha256(); size = 0
    try:
        with temporary:
            request = urllib.request.Request(record['url'], headers={'User-Agent':'zog-archive-mirror/1'})
            try:
                response = opener.open(request, timeout=60)
            except urllib.error.HTTPError as error:
                if 300 <= error.code < 400:
                    raise ValueError('Upstream redirect rejected')
                raise
            with response:
                final = response.geturl()
                if final != record['url']:
                    raise ValueError('Upstream redirect rejected')
                length = response.headers.get('Content-Length')
                if length is not None:
                    try: declared = int(length)
                    except ValueError: raise ValueError('Invalid upstream Content-Length')
                    if declared < 0 or declared > maximum: raise ValueError('Reviewed source too large')
                while True:
                    block = response.read(1024 * 1024)
                    if not block: break
                    size += len(block)
                    if size > maximum: raise ValueError('Reviewed source too large')
                    checksum.update(block); temporary.write(block)
                if length is not None and size != declared:
                    raise ValueError('Upstream size mismatch')
            temporary.flush()
        if checksum.hexdigest() != record['sha256']:
            raise ValueError('Reviewed source checksum mismatch')
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise

def populate(path, opener=None):
    data = Path(path).read_bytes()
    identity, pin_date, sources = decode_manifest(data)
    manifest_digest = hashlib.sha256(data).hexdigest()
    existing_set = SourcePinSet.objects.filter(identity=identity).first()
    if existing_set and (existing_set.manifest_sha256 != manifest_digest or existing_set.pin_date != pin_date):
        raise ValueError('Pin-set identity already names different manifest')
    pin_set, _ = SourcePinSet.objects.get_or_create(identity=identity, defaults={
        'pin_date':pin_date, 'manifest_sha256':manifest_digest})
    completed = []
    for record in sources:
        archive = _existing(record['sha256'])
        created_here = archive is None
        if created_here:
            temporary = _download(record, opener)
            try:
                archive = publish(temporary, 'sources', 'source',
                    {'reviewed_source': True, 'canonical_url': record['url']})
            finally:
                temporary.unlink(missing_ok=True)
            if archive.digest != record['sha256']:
                raise ValueError('Published reviewed source digest mismatch')
        with transaction.atomic():
            if created_here and not archive.managed:
                archive.managed = True
                archive.save(update_fields=['managed'])
            ReviewedSource.objects.get_or_create(pin_set=pin_set, archive=archive,
                package=record['package'], source=record['source'], canonical_url=record['url'])
        completed.append(archive)
    expected = {(x['sha256'],x['url'],x['package'],x['source']) for x in sources}
    actual = set(pin_set.sources.values_list('archive__digest','canonical_url','package','source'))
    if actual != expected:
        raise ValueError('Pin-set membership differs from manifest')
    pin_set.complete = True
    pin_set.active = True
    pin_set.save(update_fields=['complete','active'])
    return pin_set, completed

def deactivate(identity):
    pin_set = SourcePinSet.objects.get(identity=identity)
    pin_set.active = False
    pin_set.save(update_fields=['active'])
    return pin_set
