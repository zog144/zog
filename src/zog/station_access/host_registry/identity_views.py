import json
import uuid
from datetime import timedelta
from django.http import JsonResponse
from django.core.exceptions import RequestDataTooBig, ObjectDoesNotExist
from django.db import OperationalError
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from zog.host_identify import signatures
from . import identity
from .models import Host, HostIdentity, EnrollmentRequest, ArchivePolicy, SecurityAudit
from .views import administrator, body, validate_report, legacy_heartbeat


def response(value, status=200):
    r=JsonResponse(value,status=status);r['Cache-Control']='no-store';return r


def failure(status=401):
    return response({'detail':'Host authorization denied'},status)


@csrf_exempt
@require_POST
def enrollment(request):
    try:
        if not identity.admit(request.META.get('REMOTE_ADDR','')):
            return response({'detail':'Enrollment capacity; retry later'},429)
        data=body(request)
        if set(data) != {'public_key','claimed_host_id','report'}:
            return failure(400)
        key=signatures.public_key(data['public_key']);fingerprint=signatures.fingerprint(key)
        claimed=data['claimed_host_id']
        if claimed:claimed=str(uuid.UUID(claimed))
        if not isinstance(claimed,str):return failure(400)
        report=data['report']
        # Validate claimed report using an unpersisted host; claims confer no authority.
        cloud=report.get('cloud',{})
        if not isinstance(cloud,dict) or any(not isinstance(v,str) or len(v)>80 for v in cloud.values()):return failure(400)
        placeholder=Host(provider='aws' if cloud else 'generic',**{k:v for k,v in cloud.items() if k in {'account_id','region','instance_id'}})
        validate_report(report,placeholder,allow_host_generation=True)
        from .matching import cloud_identity
        cloud_identity(report)
        nonce,expiry=identity.proof(request,key,claimed or 'pending')
        with identity.locked():
            identity.consume(fingerprint,nonce,expiry)
            known=HostIdentity.objects.filter(pk=fingerprint).first()
            if known:
                if known.status != 'approved' or known.host.archived_at:return response({'status':'revoked'},403)
                if claimed and uuid.UUID(claimed) != known.host_id:
                    return response({'detail':'Approved identity is bound to a different host; administrator correction is required','code':'migration_target_mismatch'},409)
                return response({'status':'approved','host_id':str(known.host_id),'fingerprint':fingerprint})
            pending=EnrollmentRequest.objects.filter(pk=fingerprint).first()
            if not pending:
                if EnrollmentRequest.objects.count() >= settings_limit():
                    return response({'detail':'Enrollment capacity; retry later'},429)
                pending=EnrollmentRequest.objects.create(fingerprint=fingerprint,public_key=data['public_key'],claims=report,
                    claimed_host_id=claimed,expires_at=timezone.now()+timedelta(hours=24))
            elif pending.status=='pending' and (pending.claimed_host_id!=claimed or pending.claims!=report):
                # Only a verified proof by this same key can update untrusted pending hints.
                # Never extend the bounded expiry or change a rejected/approved binding.
                pending.claimed_host_id=claimed;pending.claims=report
                pending.save(update_fields=['claimed_host_id','claims'])
            return response({'status':pending.status,'fingerprint':fingerprint},403 if pending.status=='rejected' else 202)
    except OperationalError:return response({'detail':'Retry later'},503)
    except Exception:
        # Library exceptions can include signed material; never return/log exception text.
        return failure()


def settings_limit():
    from django.conf import settings
    return settings.HOST_PENDING_LIMIT


@csrf_exempt
@require_POST
def heartbeat(request, host_id):
    if 'Signature' not in request.headers:
        from .models import ManagedAdmission
        with identity.locked():
            if ManagedAdmission.objects.filter(host_id=host_id).exists():return failure()
            result=legacy_heartbeat(request,host_id);result['Cache-Control']='no-store';return result
    try:
        value=body(request)
        # Extensions must never be persisted in the ordinary report JSON.
        session_id=value.pop('managed_session',None)
        has_login='station_login' in value
        login=value.pop('station_login',None)
        role_status=value.pop('mirror_status',None)
        fingerprint=request.headers.get('X-Host-Key','')
        if len(fingerprint)!=64:return failure()
        # Expensive verification outside transaction, then recheck active binding under lock.
        initial=HostIdentity.objects.filter(pk=fingerprint,host_id=host_id,status='approved').first()
        if not initial:return failure()
        nonce,expiry=identity.proof(request,signatures.public_key(initial.public_key),str(host_id))
        with identity.locked():
            current=HostIdentity.objects.filter(pk=fingerprint,host_id=host_id,status='approved',public_key=initial.public_key).first()
            if not current:return failure()
            host=Host.objects.get(pk=host_id)
            if host.archived_at:return failure()
            from .managed_views import allowed
            if not allowed(host_id,fingerprint,session_id):return failure()
            validate_report(value,host,allow_host_generation=True)
            from . import vault, mirror_roles
            if has_login:vault.validate(login)
            if role_status is not None:mirror_roles.validate_status(role_status)
            identity.consume(fingerprint,nonce,expiry)
            try:
                if has_login:vault.store(host,fingerprint,login)
            except Exception:raise RuntimeError('Credential vault unavailable') from None
            if role_status is not None:mirror_roles.record(host,role_status)
            # Issuance and revocation serialize on the same write lock. No network I/O.
            try:grant=identity.archive_response(host)
            except (OSError,ValueError,KeyError,TypeError):raise RuntimeError('Archive issuer unavailable') from None
            now=timezone.now()
            # Capture only verified DNS inputs, separately from legacy/report UI data.
            # expiry includes profile skew; subtract the maximum signed lifetime
            # to retain a conservative lower bound on the authenticated creation time.
            observed = min(now, expiry - timedelta(seconds=signatures.WINDOW + signatures.SKEW))
            Host.objects.filter(pk=host_id).update(report=value,last_received=now,signed_last_received=now,
                signed_dns_report={'cloud':value.get('cloud',{}),'public_ip':value.get('public_ip','')},
                signed_dns_fingerprint=fingerprint,signed_dns_observed_at=observed)
            host.signed_last_received=now
            return response({'version':2,'host_id':str(host_id),'received_at':now,'archive':grant,'mirror_roles':mirror_roles.response(host),**({'managed_session':session_id} if session_id else {})})
    except OperationalError:return response({'detail':'Retry later'},503)
    except (OSError, RuntimeError):return response({'detail':'Authorization service unavailable'},503)
    except Exception:return failure()


@require_GET
@administrator
def administration(request):
    # No tokens, private keys, token digests, signature headers, or credential responses.
    with identity.locked():
        identity.cleanup(timezone.now())
        from .matching import resolve
        pending=[dict(fingerprint=p.fingerprint, public_key=p.public_key, claims=p.claims, claimed_host_id=p.claimed_host_id, status=p.status, expires_at=p.expires_at, match=resolve(p)) for p in EnrollmentRequest.objects.order_by('created_at')]
    keys=list(HostIdentity.objects.order_by('-approved_at').values('fingerprint','host_id','status','approved_by','approved_at','revoked_at'))
    policies=list(ArchivePolicy.objects.values('host_id','operations','collections'))
    audit=list(SecurityAudit.objects.order_by('-id').values()[:100])
    hosts=list(Host.objects.filter(archived_at__isnull=True).values('id','label','provider','instance_id','legacy_until'))
    return response({'pending':pending,'identities':keys,'policies':policies,'audit':audit,'hosts':hosts})


@require_POST
@administrator
def decision(request):
    try:
        data=body(request);action=data.get('action');fingerprint=data.get('fingerprint','')
        actor=str(request.user.pk)+':'+request.user.get_username()
        if action=='approve':
            host=identity.approve(actor,fingerprint,data.get('confirmed_fingerprint'),data.get('host_id') or None)
            return response({'saved':True,'host_id':str(host.id)})
        if action=='reject':identity.reject(actor,fingerprint)
        elif action=='revoke':identity.revoke(actor,fingerprint)
        elif action=='policy':identity.set_policy(actor,data['host_id'],data['operations'],data['collections'])
        else:return response({'detail':'Unknown action'},400)
        return response({'saved':True})
    except identity.MigrationTargetError as error:
        return response({'detail':str(error),'code':'migration_target_mismatch'},400)
    except (ValueError,KeyError,TypeError,ObjectDoesNotExist,RequestDataTooBig):
        return response({'detail':'Invalid decision or state; refresh and check fingerprint/host selection'},400)
    except OperationalError:return response({'detail':'Retry later'},503)
