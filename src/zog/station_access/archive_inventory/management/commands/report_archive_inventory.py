"""Explicit read-only observation job; never installs, elects, starts or stops services."""
import json
import time
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify.signatures import origin, sign
from zog.host_identify.storage import read_owned


class Command(BaseCommand):
    help = 'Report local archive-mirror catalog using an existing approved host identity and verified HTTPS.'

    def add_arguments(self, parser):
        parser.add_argument('--configuration', required=True, help='Owner-only reporting configuration JSON')

    def handle(self, *args, **options):
        try:
            config = json.loads(read_owned(Path(options['configuration']), 0o600))
            if set(config)-{'registry', 'identity_key', 'ca_file', 'controller_project', 'application', 'observation_version'}:
                raise ValueError('Unknown configuration')
            registry = origin(config['registry'])
            ca = config.get('ca_file') or True
            if ca is not True and not isinstance(ca, str):
                raise ValueError('Certificate verification required')
            key = serialization.load_pem_private_key(read_owned(Path(config['identity_key']), 0o600), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError('Ed25519 key required')
            from zog.archive_mirror.observation import observe
            version = config.get('observation_version', 1)
            value = observe(version=version)
            value['preparation'] = preparation(config)
            items = value.pop('items')
            value['total'] = len(items)
            url = registry + '/api/archives/reports/' + value['host_id'] + '/'
            import requests
            deadline = time.monotonic() + 240
            with requests.Session() as session:
                session.trust_env = False
                for offset in range(0, max(1, len(items)), 100):
                    if time.monotonic() >= deadline:
                        raise ValueError('Report deadline exceeded')
                    page = dict(value, offset=offset, items=items[offset:offset+100])
                    body = json.dumps(page, separators=(',', ':')).encode()
                    message = sign(url, body, key, value['host_id'])
                    with session.send(message, timeout=(5, 20), verify=ca, allow_redirects=False, stream=True) as result:
                        if result.status_code != 200:
                            raise ValueError('Report rejected')
                        if version == 2:
                            reply = result.raw.read(32769)
                            if len(reply) > 32768:
                                raise ValueError('Report response too large')
                            missing = json.loads(reply).get('missing_notices', [])
                            upload_notices(session, registry, key, ca, value['host_id'], page['items'], missing, deadline)
            self.stdout.write('Archive observation reported: ' + value['status'])
        except Exception:
            # Network exceptions may contain URLs; never expose exception text or body.
            raise CommandError('Archive observation could not be reported; check identity, configuration, store and connectivity.') from None


def preparation(config):
    """Read only the public controller inspection API; never refresh/prepare/recover."""
    unknown = dict(state='unknown', attempt_id=None)
    if not config.get('controller_project'):
        return unknown
    try:
        project = Path(config['controller_project'])
        if not project.is_absolute():
            return unknown
        from zog.box_control.api import BoxControl
        from zog.box_control.project import Project
        row = BoxControl(Project(project)).application_preparation(config.get('application', 'station-access'))
        if not row:
            return unknown
        import re
        if row.get('state') not in {'preparing', 'ready', 'failed', 'uncertain', 'deleting', 'deleted'} or not re.fullmatch(r'[0-9a-f]{32}', row.get('attempt_id', '')):
            return unknown
        return dict(state=row['state'], attempt_id=row['attempt_id'])
    except Exception:
        return unknown


def upload_notices(session, registry, key, ca, host, items, missing, deadline):
    from zog.archive_mirror import notices, notice_contract as c
    from zog.archive_mirror.models import Archive
    if not isinstance(missing, list) or len(missing) > 100:
        raise ValueError('Invalid notice requests')
    allowed = {(r['collection'], r['digest'], r['licenses'].get('bundle_digest')) for r in items}
    for row in missing:
        c.exact(row, 'collection digest bundle_digest')
        if (row['collection'], row['digest'], row['bundle_digest']) not in allowed or time.monotonic() >= deadline:
            raise ValueError('Unobserved notice request or deadline exceeded')
        archive = Archive.objects.get(collection=row['collection'], digest=row['digest'])
        value = notices.read(archive)
        body = c.canonical(value)
        if c.digest(body) != row['bundle_digest']:
            raise ValueError('Notice changed')
        url = registry + '/api/archives/reports/' + host + '/notices/'
        message = sign(url, body, key, host)
        with session.send(message, timeout=(5, 20), verify=ca, allow_redirects=False, stream=True) as result:
            if result.status_code != 200:
                raise ValueError('Notice upload rejected')
