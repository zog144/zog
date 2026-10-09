"""Approved-host managed sessions; serialize with enrollment/revocation/heartbeat."""
import re
import time
import uuid
from pathlib import Path
from django.conf import settings
from django.db import OperationalError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import signatures, managed, storage
from . import identity
from .identity_views import body, response, failure
from .models import Host, HostIdentity, ManagedAdmission


def signer():
    # Explicit dedicated station control key; never archive/release signing keys.
    path=Path(settings.HOST_MANAGED_SIGNING_KEY_FILE)
    storage.directory(path.parent)
    key=serialization.load_pem_private_key(storage.read_owned(path,0o600),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise ValueError('Ed25519 required')
    return key


def parse(value):
    if type(value) is not dict or set(value)!={'version','installation_id','state_volume_id','authority_id','registry_id','challenge','previous','boot_id'} or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Invalid admission request')
    for name in ('installation_id','state_volume_id','authority_id','challenge','boot_id'):managed.identifier(value[name])
    if not isinstance(value['registry_id'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}',value['registry_id']):raise ValueError('Invalid registry')
    previous=value['previous']
    if previous is not None:
        if type(previous) is not dict or set(previous)!={'epoch','checkpoint'} or type(previous['epoch']) is not int or previous['epoch']<1:raise ValueError('Invalid checkpoint')
        managed.identifier(previous['checkpoint'])
    return value


def allowed(host_id, fingerprint, session_id):
    row=ManagedAdmission.objects.filter(host_id=host_id).first()
    if row is None:return session_id is None
    return (row.fingerprint==fingerprint and type(session_id) is str and
            row.claims.get('jti')==session_id and time.time()<row.claims.get('exp',0))


@csrf_exempt
@require_POST
def establish(request,host_id):
    if not getattr(settings,'HOST_MANAGED_ADMISSION_ENABLED',False):
        return response({'code':'managed-admission-disabled'},503)
    try:
        value=parse(body(request))
        authority=managed.identifier(settings.HOST_MANAGED_AUTHORITY_ID)
        if value['authority_id']!=authority:raise ValueError('Wrong authority')
        fp=request.headers.get('X-Host-Key','')
        initial=HostIdentity.objects.filter(pk=fp,host_id=host_id,status='approved').first()
        if initial is None:return failure()
        nonce,expiry=identity.proof(request,signatures.public_key(initial.public_key),str(host_id))
        key=signer()
        with identity.locked():
            current=HostIdentity.objects.filter(pk=fp,host_id=host_id,status='approved',public_key=initial.public_key).first()
            host=Host.objects.get(pk=host_id)
            if current is None or host.archived_at:return failure()
            identity.consume(fp,nonce,expiry)
            row=ManagedAdmission.objects.filter(host=host).first()
            fixed={'fingerprint':fp,**{name:value[name] for name in ('installation_id','state_volume_id','authority_id','registry_id')}}
            if row:
                if any(str(getattr(row,k))!=v for k,v in fixed.items()):
                    return response({'code':'managed-binding-conflict'},409)
                if row.request==value:
                    # Re-sign exactly the same claims after a lost response, never
                    # extend an expired session or accept a new HTTP replay nonce.
                    if time.time()>=row.claims['exp']:return response({'code':'managed-recovery-required'},409)
                    claims=row.claims
                else:
                    if value['previous']!={'epoch':row.epoch,'checkpoint':str(row.checkpoint)}:
                        return response({'code':'managed-checkpoint-conflict'},409)
                    claims=None
            else:
                if value['previous'] is not None:return response({'code':'managed-station-history-missing'},409)
                claims=None
            if claims is None:
                now=int(time.time());epoch=(row.epoch if row else 0)+1
                claims=dict(iss=signatures.origin(settings.HOST_IDENTITY_ORIGIN),aud=authority,sub=str(host_id),
                    iat=now,exp=now+managed.LIFETIME,jti=str(uuid.uuid4()),epoch=epoch,checkpoint=str(uuid.uuid4()),
                    fingerprint=fp,installation_id=value['installation_id'],state_volume_id=value['state_volume_id'],
                    registry_id=value['registry_id'],challenge=value['challenge'],previous=value['previous'],
                    boot_id=value['boot_id'],operations=['inspect'])
                if row is None:row=ManagedAdmission(host=host,**fixed)
                row.epoch=epoch;row.checkpoint=claims['checkpoint'];row.request=value;row.claims=claims;row.save()
                identity.audit('managed-host','managed-session-established',fp,host,epoch=epoch)
            return response({'version':1,'public_key':signatures.public_text(key.public_key()),
                'session':managed.sign(claims,key,managed.SESSION_TYPE)})
    except OperationalError:return response({'code':'managed-retry'},503)
    except (AttributeError,OSError,RuntimeError):return response({'code':'managed-unavailable'},503)
    except Exception:return failure()


@csrf_exempt
@require_POST
def reconcile(request,host_id):
    """Read-only checkpoint evidence for the exact accepted, expired request.

    Authentication consumes a fresh HTTP nonce; no epoch/session/history changes.
    A local root operator separately authorizes adopting the evidence.
    """
    from zog.host_identify import recovery
    if not getattr(settings,'HOST_MANAGED_ADMISSION_ENABLED',False):
        return response({'code':'managed-admission-disabled'},503)
    try:
        value=body(request)
        if type(value) is not dict or set(value)!={'version','operation_id','journal_sha256','pending'} or type(value['version']) is not int or value['version']!=1:
            raise ValueError('Invalid recovery request')
        operation=managed.identifier(value['operation_id']);pending=parse(value['pending'])
        if not isinstance(value['journal_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['journal_sha256']):raise ValueError('Invalid digest')
        authority=managed.identifier(settings.HOST_MANAGED_AUTHORITY_ID)
        if pending['authority_id']!=authority:raise ValueError('Wrong authority')
        fp=request.headers.get('X-Host-Key','')
        initial=HostIdentity.objects.filter(pk=fp,host_id=host_id,status='approved').first()
        if initial is None:return failure()
        nonce,expiry=identity.proof(request,signatures.public_key(initial.public_key),str(host_id))
        key=signer()
        with identity.locked():
            current=HostIdentity.objects.filter(pk=fp,host_id=host_id,status='approved',public_key=initial.public_key).first()
            host=Host.objects.get(pk=host_id)
            if current is None or host.archived_at:return failure()
            identity.consume(fp,nonce,expiry)
            row=ManagedAdmission.objects.filter(host=host).first()
            fixed={'fingerprint':fp,**{name:pending[name] for name in ('installation_id','state_volume_id','authority_id','registry_id')}}
            if row is None or row.request!=pending or any(str(getattr(row,k))!=v for k,v in fixed.items()):
                return response({'code':'managed-recovery-history-conflict'},409)
            expected=dict(iss=signatures.origin(settings.HOST_IDENTITY_ORIGIN),aud=authority,sub=str(host_id),fingerprint=fp,
                **{name:pending[name] for name in ('installation_id','state_volume_id','registry_id','challenge','previous','boot_id')})
            if any(row.claims.get(k)!=v for k,v in expected.items()) or type(row.claims.get('iat')) is not int or type(row.claims.get('exp')) is not int or not 0<row.claims['exp']-row.claims['iat']<=managed.LIFETIME:
                return response({'code':'managed-recovery-history-conflict'},409)
            now=int(time.time())
            if now<row.claims['exp']:return response({'code':'managed-session-not-expired'},409)
            if row.epoch!=(pending['previous']['epoch']+1 if pending['previous'] else 1) or row.claims['epoch']!=row.epoch or row.claims['checkpoint']!=str(row.checkpoint):
                return response({'code':'managed-recovery-history-conflict'},409)
            claims=dict(iss=signatures.origin(settings.HOST_IDENTITY_ORIGIN),aud=authority,sub=str(host_id),
                iat=now,exp=now+managed.LIFETIME,jti=operation,operation_id=operation,
                journal_sha256=value['journal_sha256'],request_sha256=recovery.digest(pending),
                fingerprint=fp,installation_id=pending['installation_id'],state_volume_id=pending['state_volume_id'],
                registry_id=pending['registry_id'],epoch=row.epoch,checkpoint=str(row.checkpoint),
                session_expired_at=row.claims['exp'])
            return response({'version':1,'public_key':signatures.public_text(key.public_key()),
                'evidence':managed.sign(claims,key,recovery.TYPE)})
    except OperationalError:return response({'code':'managed-retry'},503)
    except (AttributeError,OSError,RuntimeError):return response({'code':'managed-unavailable'},503)
    except Exception:return failure()
