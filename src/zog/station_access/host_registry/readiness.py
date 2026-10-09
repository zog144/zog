"""Read local configuration and recorded observations only; never start or reconcile services."""
import json
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http.request import validate_host
from django.utils import timezone
from urllib.parse import urlsplit
from . import vault, provider_checks
from .models import (ProviderCredential, BeaconDestination, InventoryScan, Host, EnrollmentRequest,
                     DnsAssignment, MirrorRole)


def recent(stamp, now, seconds):
    return bool(stamp and 0 <= (now - stamp).total_seconds() <= seconds)


def snapshot():
    now = timezone.now()
    checks = []
    def add(identifier, title, area, status, detail, link='', observed_at=None):
        checks.append(dict(id=identifier, title=title, area=area, status=status, detail=detail, link=link, observed_at=observed_at))

    count = get_user_model().objects.filter(is_active=True, is_superuser=True).count()
    add('administrators', 'Administrator accounts', 'Local station', 'configured' if count else 'needs_attention',
        f'{count} active administrator account(s). Password recovery and rotation are not checked.')
    if not settings.HOST_VAULT_CONFIGURATION:
        add('vault', 'Credential vault', 'Local station', 'not_configured', 'No protected keyring is configured.', '/registries')
    else:
        try:
            vault.keyring()
            add('vault', 'Credential vault', 'Local station', 'configured', 'Protected keyring is readable and valid. Backup recoverability is not checked.', '/registries')
        except Exception:
            add('vault', 'Credential vault', 'Local station', 'needs_attention', 'Protected keyring is missing, unreadable or invalid. Restore the existing keyring before using saved credentials.', '/registries')

    if not settings.HOST_IDENTITY_ORIGIN:
        add('https', 'Public HTTPS configuration', 'Central registry', 'not_configured', 'No signed-registry HTTPS origin is configured. Local-only portal use may not require one.')
    else:
        try:
            from .setup_configuration import origin
            host = urlsplit(origin(settings.HOST_IDENTITY_ORIGIN)).hostname
            valid = validate_host(host, settings.ALLOWED_HOSTS) and not settings.DEBUG and settings.SESSION_COOKIE_SECURE and '*' not in settings.ALLOWED_HOSTS
            add('https', 'Public HTTPS configuration', 'Central registry', 'configured' if valid else 'needs_attention',
                'HTTPS origin, host allowlist and secure-session settings are configured. Certificate validity, renewal and firewall reachability are not checked.' if valid else
                'Review the HTTPS origin, host allowlist, debug mode and secure-session settings. Certificate and firewall checks still require deployment verification.')
        except Exception:
            add('https', 'Public HTTPS configuration', 'Central registry', 'needs_attention', 'The signed-registry HTTPS origin is invalid.')

    providers = list(ProviderCredential.objects.order_by('label'))
    supported = [p for p in providers if p.provider in ('cloudflare', 'porkbun')]
    observations = [provider_checks.serialize(p, now) for p in supported]
    confirmed = [c for c in observations if c['status'] == 'passed' and c['fresh']]
    add('providers', 'Domain provider access', 'Central registry', 'needs_attention' if any(c['status'] in ('failed', 'interrupted', 'outdated', 'no_domains') for c in observations) else 'observed' if confirmed else 'configured' if providers else 'not_configured',
        f'{len(providers)} saved account(s); {len(confirmed)} have a recent successful domain-list check. DNS-write permission is not verified. Porkbun domain listing is available; its automatic DNS reconciliation is not enabled.',
        '/registries', max((c['finished_at'] for c in confirmed), default=None))
    destinations = BeaconDestination.objects.all()
    add('destinations', 'Beacon destination deployment', 'Central registry', 'configured' if destinations.exists() else 'not_configured',
        f'{destinations.filter(enabled=True).count()} enabled destination(s) saved. Installation acknowledgement is unavailable; a saved list does not prove any beaconer is using it.', '/deployments')

    try:
        from .dns_reconcile import configuration
        from .setup_configuration import cloudflare_credentials
        config = configuration()
        if config:
            root = Path(config['state_directory'])
            with (root / 'controller.json').open() as stream:
                binding = json.loads(stream.read(65537))
            expected = {'schema': 1, 'domain': config['domain'], 'suffix': config['suffix'], 'account_id': config['account_id']}
            if binding != expected or not (root / 'network-register').is_dir():raise ValueError('Controller state mismatch')
            account, _ = cloudflare_credentials(config)
            if account != config['account_id']:raise ValueError('Credential account mismatch')
            add('dns-controller', 'Authoritative DNS controller', 'Central registry', 'configured', 'Domain binding, persistent ownership directory and configured credential are readable. The writer lock and remote provider are not exercised by this page.', '/registries')
        else:
            add('dns-controller', 'Authoritative DNS controller', 'Central registry', 'not_configured', 'Initialize the domain, suffix and persistent single-controller ownership state before DNS publication.', '/registries')
    except Exception:
        add('dns-controller', 'Authoritative DNS controller', 'Central registry', 'needs_attention', 'DNS configuration, credential or ownership state is unavailable or inconsistent. Restore it; do not recreate ownership state over existing records.', '/registries')

    scans = list(InventoryScan.objects.all())
    discovery = next((s for s in scans if s.scope == 'region-discovery'), None)
    regions = [s for s in scans if s.scope != 'region-discovery']
    complete = bool(discovery and recent(discovery.last_success, now, 600) and not discovery.error and regions and all(
        recent(s.last_success, now, 600) and not s.error and s.last_success >= discovery.last_success for s in regions))
    add('inventory', 'AWS inventory observations', 'Central registry', 'observed' if complete else 'needs_attention' if scans else 'not_checked',
        f'{len(regions)} region scan record(s). ' + ('Recorded scans are successful and recent (within ten minutes).' if complete else 'Inventory is absent, partial, failed or stale; it cannot establish that an instance stopped.'),
        '/hosts', min((s.last_success for s in scans if s.last_success), default=None) if complete else None)
    approved = list(Host.objects.filter(archived_at__isnull=True, identities__status='approved').distinct())
    reporting = [h for h in approved if recent(h.signed_last_received, now, 180)]
    pending = EnrollmentRequest.objects.filter(status='pending', expires_at__gt=now).count()
    add('beacons', 'Signed host observations', 'Central registry', 'observed' if reporting else 'needs_attention' if approved else 'not_configured',
        f'{len(reporting)} of {len(approved)} approved host(s) reported within three minutes; {pending} pending request(s). Missing reports alone do not prove a stopped host.',
        '/host-identities', max((h.signed_last_received for h in reporting), default=None))
    assignments = list(DnsAssignment.objects.all())
    current = [a for a in assignments if a.status in ('synchronized', 'unpublished') and a.applied_revision == a.revision and recent(a.last_success, now, 600)]
    add('dns-observations', 'DNS reconciliation observations', 'Central registry', 'observed' if assignments and len(current) == len(assignments) else 'needs_attention' if assignments else 'not_checked',
        f'{len(current)} of {len(assignments)} assignment(s) have a successful reconciliation within ten minutes. This is recorded evidence, not a new public DNS lookup.',
        '/hosts', min((a.last_success for a in current), default=None))

    project = settings.STATION_ACCESS_ZOG_PROJECT_DIRECTORY
    try:project_present = bool(project and Path(project).is_dir())
    except OSError:project_present = False
    add('controller', 'Controller and root filesystem', 'Local station', 'configured' if project_present else 'needs_attention' if project else 'not_configured',
        'A configured project directory is present; root-control availability, generation integrity and launch readiness are not checked.' if project_present else
        'No accessible explicit controller project directory is configured. Automatic project discovery and root filesystem readiness are not evaluated.')
    from zog.station_access.models import VncWorkspace
    from zog.station_access.services import workspace_applications
    block = getattr(workspace_applications, 'LAUNCH_BLOCK', {})
    blocked = block.get('available') is False
    add('workspaces', 'Graphical workspace launch', 'Local station', 'blocked' if blocked else 'not_checked',
        f'{VncWorkspace.objects.count()} workspace record(s). ' +
        ('Application launch is awaiting the durable controller workspace/display/network attachment contract. No desktop was started by this check.' if blocked else
         'Workspace launch and graphical connectivity are not probed here.'), '/workspaces')

    archive_path = settings.HOST_ARCHIVE_CONFIGURATION
    try:archive_configured = bool(archive_path and Path(archive_path).is_file())
    except OSError:archive_configured = False
    add('archive-issuer', 'Archive authorization issuer', 'Optional services', 'configured' if archive_configured else 'needs_attention' if archive_path else 'not_configured',
        'Issuer configuration file is present; signing-key validity, rotation and consumer verification are not checked.' if archive_configured else
        'No accessible issuer configuration file. Archive policy defaults to no access.', '/host-identities')
    roles = list(MirrorRole.objects.filter(selected=True).select_related('host'))
    ready_roles = [r for r in roles if not r.host.archived_at and r.host.identities.filter(status='approved').exists() and
                   r.acknowledged_revision == r.revision and r.reported_state == 'ready' and recent(r.observed_at, now, 180) and recent(r.host.signed_last_received, now, 180)]
    add('mirrors', 'Archive mirror observations', 'Optional services', 'observed' if roles and len(ready_roles) == len(roles) else 'needs_attention' if roles else 'not_configured',
        f'{len(ready_roles)} of {len(roles)} selected mirror(s) have a recent matching readiness report. No download or lifecycle test was performed.', '/hosts',
        min((r.observed_at for r in ready_roles), default=None))
    add('recovery', 'Backup and recovery', 'Local station', 'not_checked', 'There is no backup-verification interface yet. Confirm database, protected keys and controller state can be recovered together.')
    return {'server_time': now, 'read_only': True, 'checks': checks}
