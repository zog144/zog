"""All security state transitions take the same database write lock FIRST."""
import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path
from contextlib import contextmanager
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import signatures, archive
from .models import (SecurityGate, EnrollmentRequest, HostIdentity, Host, ReplayRecord,
                     AdmissionWindow, SecurityAudit, ArchivePolicy)


class MigrationTargetError(ValueError):
    pass


@contextmanager
def locked():
    with transaction.atomic():
        if SecurityGate.objects.filter(pk=1).update(revision=F('revision')+1) != 1:
            raise RuntimeError('Security gate migration missing')
        yield


def audit(actor, action, fingerprint='', host=None, **details):
    SecurityAudit.objects.create(actor=str(actor), action=action, fingerprint=fingerprint,
                                host_id_text=str(host.pk) if host else '', details=details)


def cleanup(now):
    ReplayRecord.objects.filter(expires_at__lt=now).delete()
    AdmissionWindow.objects.filter(expires_at__lt=now).delete()
    EnrollmentRequest.objects.filter(expires_at__lt=now).delete()


def admit(address):
    # Apply before expensive signature verification. Never trust X-Forwarded-For.
    with locked():
        now = timezone.now(); cleanup(now)
        key = hashlib.sha256(address.encode()).hexdigest()
        for bucket, limit in [('global',settings.HOST_ENROLLMENT_PER_MINUTE), ('ip:'+key,settings.HOST_ENROLLMENT_PER_ADDRESS)]:
            row, _ = AdmissionWindow.objects.get_or_create(bucket=bucket, defaults={'expires_at':now+timedelta(minutes=1)})
            if row.count >= limit:
                return False
            row.count += 1; row.save(update_fields=['count'])
        return True


def consume(fingerprint, nonce, expiry):
    now = timezone.now()
    if expiry < now:raise ValueError('Signature expired while waiting for commit')
    cleanup(now)
    if ReplayRecord.objects.count() >= settings.HOST_REPLAY_LIMIT:
        raise ValueError('Replay storage capacity reached')
    if ReplayRecord.objects.filter(fingerprint=fingerprint, nonce=nonce).exists():
        raise ValueError('Replayed request')
    ReplayRecord.objects.create(fingerprint=fingerprint, nonce=nonce, expires_at=expiry)


def external_url(request):
    base = signatures.origin(settings.HOST_IDENTITY_ORIGIN)
    # The proxy must preserve Host and path. The canonical configured HTTPS origin
    # supplies scheme; no caller-controlled forwarded URL is used for signatures.
    from urllib.parse import urlsplit
    if request.get_host().lower() != urlsplit(base).netloc.lower() or request.META.get('QUERY_STRING'):
        raise ValueError('Incorrect destination')
    return base + request.path


def proof(request, key, subject):
    return signatures.verify(external_url(request), request.method, request.headers, request.body, key, subject)


def approve(actor, fingerprint, confirmed, target=None):
    if confirmed != fingerprint:
        raise ValueError('Confirm the full fingerprint from a trusted channel')
    with locked():
        known = HostIdentity.objects.select_related('host').filter(pk=fingerprint).first()
        if known:
            original_new = SecurityAudit.objects.filter(action='approve-key', fingerprint=fingerprint, details__created_host=True).exists()
            same = (target and uuid.UUID(str(target)) == known.host_id) or (not target and original_new)
            if known.status == 'approved' and same and not known.host.archived_at:
                return known.host
            raise MigrationTargetError('Fingerprint is already bound to another host or is revoked; no transfer is permitted')
        pending = EnrollmentRequest.objects.get(pk=fingerprint, status='pending', expires_at__gt=timezone.now())
        from .matching import resolve
        match = resolve(pending)
        if match['status'] == 'conflict':
            raise MigrationTargetError(match['reason'])
        if match['status'] == 'existing':
            if not target or str(uuid.UUID(str(target))) != match['host']['id']:
                raise MigrationTargetError('Matching changed or a different host was selected; refresh and approve the proposed existing host')
            host = Host.objects.get(pk=target)
        else:
            if target:
                raise MigrationTargetError('No matching existing host; arbitrary binding is not permitted')
            host = Host.objects.create(label=pending.claims.get('hostname', '')[:200],
                                       provider='aws' if match['cloud'] else 'generic', **(match['cloud'] or {}))
        if HostIdentity.objects.filter(host=host, status='approved').exists():
            raise ValueError('Revoke the existing key explicitly before approving a replacement')
        HostIdentity.objects.create(fingerprint=fingerprint, public_key=pending.public_key, host=host,
                                   approved_by=str(actor), approved_at=timezone.now())
        host.signed_last_received = None
        host.legacy_until = None
        host.token_revoked = True
        host.save(update_fields=['signed_last_received','legacy_until','token_revoked'])
        pending.delete()
        audit(actor, 'approve-key', fingerprint, host, created_host=match['status']=='new', matching_reason=match['reason'])
        return host


def reject(actor, fingerprint):
    with locked():
        pending = EnrollmentRequest.objects.get(pk=fingerprint, status='pending')
        pending.status='rejected'; pending.expires_at=timezone.now()+timedelta(days=30); pending.save()
        audit(actor,'reject-key',fingerprint)


def revoke(actor, fingerprint):
    with locked():
        identity=HostIdentity.objects.get(pk=fingerprint, status='approved')
        identity.status='revoked'; identity.revoked_at=timezone.now();identity.save()
        Host.objects.filter(pk=identity.host_id).update(signed_last_received=None, token_revoked=True, legacy_until=None)
        audit(actor,'revoke-key',fingerprint,identity.host)


def set_policy(actor, host_id, operations, collections):
    operations, collections = archive.permissions(operations, collections)
    with locked():
        host=Host.objects.get(pk=host_id)
        if host.archived_at:raise ValueError('Restore archived host first')
        ArchivePolicy.objects.update_or_create(host=host, defaults={'operations':operations,'collections':collections})
        audit(actor,'archive-policy',host=host,operations=operations,collections=collections)


def archive_response(host):
    policy=ArchivePolicy.objects.filter(host=host).first()
    if not policy or not policy.operations or not policy.collections:
        return None  # Explicit withdrawal: daemon deletes its local credential.
    config=json.loads(Path(settings.HOST_ARCHIVE_CONFIGURATION).read_text())
    mirror=signatures.origin(config['mirror'])
    path=Path(config['private_key_file'])
    import stat, os
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Signing key requires owner-only regular file')
    from zog.host_identify.storage import read_owned
    key=serialization.load_pem_private_key(read_owned(path,0o600),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise ValueError('Ed25519 signing key required')
    token,expiry=archive.issue(key,config['key_id'],config['issuer'],config['audience'],host.id,policy.operations,policy.collections)
    return {'version':1,'format':'zog-archive-jwt-v1','mirror':mirror,'token':token,'expires_at':expiry,
            'issuer':config['issuer'],'audience':config['audience']}
