import json
import time
import uuid
from django.db import IntegrityError, OperationalError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from zog.host_identify import signatures
from zog.station_access.host_registry import identity, mirror_roles
from zog.station_access.host_registry.models import HostIdentity, MirrorRole
from zog.station_access.host_registry.views import administrator
from . import contract
from .models import Observation, Entry


def response(value, status=200):
    result = JsonResponse(value, status=status)
    result['Cache-Control'] = 'no-store'
    result['X-Content-Type-Options'] = 'nosniff'
    return result


def persist(host, value, at):
    """Caller holds the security lock. Stage ordered pages, publish atomically."""
    role = MirrorRole.objects.get(host=host)
    if value['host_id'] != str(host.id) or role.revision != value['role_revision']:
        raise ValueError('Role mismatch')
    observation_id = uuid.UUID(value['observation_id'])
    header = {k: value[k] for k in ['role_revision', 'status', 'serving', 'lease_expires_at', 'summary', 'total', 'preparation']}
    header['schema_version'] = value['version']
    if value['offset'] == 0:
        newest = Observation.objects.filter(host=host).order_by('-observed_at').first()
        if newest and at <= newest.observed_at:
            raise ValueError('Superseded observation')
        # Keep last complete success plus last completed failure while staging one
        # newer snapshot. Repeated abandoned uploads cannot grow storage unbounded.
        keep = list(Observation.objects.filter(host=host, complete=True, status='ok').order_by('-observed_at').values_list('id', flat=True)[:1])
        keep += list(Observation.objects.filter(host=host, complete=True).order_by('-observed_at').values_list('id', flat=True)[:1])
        Observation.objects.filter(host=host).exclude(id__in=keep).delete()
        row = Observation.objects.create(id=observation_id, host=host, observed_at=at, **header)
    else:
        row = Observation.objects.get(id=observation_id, host=host, complete=False)
        if row.observed_at != at or any(getattr(row, k) != v for k, v in header.items()):
            raise ValueError('Snapshot changed')
    if row.entries.count() != value['offset']:
        raise ValueError('Out of order page')
    Entry.objects.bulk_create([Entry(observation=row, position=value['offset']+i, collection=item['collection'], digest=item['digest'], metadata=item) for i, item in enumerate(value['items'])])
    if value['offset']+len(value['items']) == row.total:
        # Compute logical totals from the complete catalogue, not publisher totals.
        metadata = list(row.entries.values_list('metadata', flat=True))
        sizes = [item['size_bytes'] for item in metadata]
        distinct = {}
        consistent = True
        for item in metadata:
            if item['digest'] in distinct and distinct[item['digest']] != item['size_bytes']:
                consistent = False
            distinct[item['digest']] = item['size_bytes']
        row.summary['logical_bytes'] = sum(sizes) if row.status == 'ok' and None not in sizes else None
        row.summary['unique_content_bytes'] = sum(distinct.values()) if row.status == 'ok' and consistent and None not in distinct.values() else None
        row.complete = True
        row.save(update_fields=['complete', 'summary'])
        keep = [row.id]
        keep += list(Observation.objects.filter(host=host, complete=True, status='ok').order_by('-observed_at').values_list('id', flat=True)[:1])
        Observation.objects.filter(host=host).exclude(id__in=keep).delete()
    return row.complete


@csrf_exempt
@require_POST
def report(request, host_id):
    # Machine ingestion only. Browser sessions and archive download JWTs confer no
    # permission to replace observations; require approved exact-key host proof.
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > contract.MAX_BODY or len(request.body) > contract.MAX_BODY:
            return response({'detail': 'Observation too large'}, 413)
        value = json.loads(request.body)
        at = contract.validate(value)
        fingerprint = request.headers.get('X-Host-Key', '')
        initial = HostIdentity.objects.filter(pk=fingerprint, host_id=host_id, status='approved', host__archived_at__isnull=True).first()
        if not initial:
            return response({'detail': 'Host authorization denied'}, 401)
        nonce, expiry = identity.proof(request, signatures.public_key(initial.public_key), str(host_id))
        with identity.locked():
            current = HostIdentity.objects.select_related('host').get(pk=fingerprint, host_id=host_id, status='approved', public_key=initial.public_key, host__archived_at__isnull=True)
            identity.consume(fingerprint, nonce, expiry)
            complete = persist(current.host, value, at)
        from .notice_views import missing
        return response({'accepted': True, 'complete': complete, **({'missing_notices': missing(host_id, value['items'])} if value['version'] == 2 else {})})
    except OperationalError:
        return response({'detail': 'Observation store unavailable'}, 503)
    except Exception:
        # No exception text, request body or signature logging.
        return response({'detail': 'Invalid or unauthorized observation'}, 400)


def limit(request):
    value = int(request.GET.get('limit', '25'))
    if not 1 <= value <= 100:
        raise ValueError('Invalid limit')
    if any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ValueError('Duplicate parameter')
    return value


def describe(role):
    latest = Observation.objects.filter(host=role.host, complete=True).order_by('-observed_at').first()
    good = Observation.objects.filter(host=role.host, complete=True, status='ok').order_by('-observed_at').first()
    now = timezone.now()
    approved = role.host.identities.filter(status='approved').exists() and not role.host.archived_at
    fresh = bool(good and approved and good.role_revision == role.revision and 0 <= (now-good.observed_at).total_seconds() <= contract.MAX_AGE)
    health = 'unavailable' if not latest else ('stale' if not fresh else 'observed')
    if latest and latest.status != 'ok':
        health = 'unavailable' if (now-latest.observed_at).total_seconds() <= contract.MAX_AGE else 'stale'
    role_state = mirror_roles.serialize(role.host, now)
    serving = bool(fresh and (now-good.observed_at).total_seconds() <= 45 and health == 'observed' and role.selected and good.serving and good.lease_expires_at and time.time() < good.lease_expires_at)
    prep = latest.preparation if latest else {'state': 'unknown', 'attempt_id': None}
    prep_fresh = bool(latest and latest.role_revision == role.revision and approved and 0 <= (now-latest.observed_at).total_seconds() <= contract.MAX_AGE)
    state = 'serving' if serving else 'assigned'
    if not role.selected:
        state = 'not-selected'
    elif not approved:
        state = 'blocked'
    elif prep_fresh and prep['state'] in {'failed', 'uncertain'} and not serving:
        state = 'blocked'
    elif prep_fresh and prep['state'] == 'preparing' and not serving:
        state = 'preparing'
    elif role_state['state'] in {'blocked', 'failed'} and not role_state['stale']:
        state = 'blocked'
    elif role_state['state'] == 'starting' and not role_state['stale']:
        state = 'starting'
    elif health == 'stale' or (good and good.serving and not serving):
        state = 'stale'
    return dict(host_id=str(role.host_id), name=role.host.label or str(role.host_id), selected=role.selected,
        role_revision=role.revision, state=state, reason=role_state['reason'], observation_state=health,
        preparation=dict(prep, fresh=prep_fresh),
        observed_at=good.observed_at if good else None, last_attempt_at=latest.observed_at if latest else None,
        observation_revision=good.role_revision if good else None, role_observed_at=role.observed_at,
        snapshot=str(good.id) if good else None, archive_count=good.total if good else None,
        summary=good.summary if good else None)


@never_cache
@require_GET
@administrator
def mirrors(request):
    try:
        size = limit(request)
        if set(request.GET)-{'limit', 'after'}:
            raise ValueError('Unknown parameter')
        rows = MirrorRole.objects.select_related('host').order_by('host_id')
        if request.GET.get('after'):
            rows = rows.filter(host_id__gt=uuid.UUID(request.GET['after']))
        rows = list(rows[:size+1])
        return response(dict(version=1, freshness_seconds=contract.MAX_AGE, mirrors=[describe(row) for row in rows[:size]], next_cursor=str(rows[size-1].host_id) if len(rows)>size else None))
    except (ValueError, TypeError):
        return response({'detail': 'Invalid pagination'}, 400)


@never_cache
@require_GET
@administrator
def items(request):
    try:
        size = limit(request)
        if set(request.GET)-{'limit', 'mirror', 'snapshot', 'after', 'collection'}:
            raise ValueError('Unknown parameter')
        host = uuid.UUID(request.GET['mirror'])
        snapshot = uuid.UUID(request.GET['snapshot'])
        after = int(request.GET.get('after', '-1'))
        if not -1 <= after < contract.MAX_ITEMS:
            raise ValueError('Invalid cursor')
        observation = Observation.objects.get(pk=snapshot, host_id=host, complete=True, status='ok')
        rows = observation.entries.filter(position__gt=after).order_by('position')
        collection = request.GET.get('collection')
        if collection:
            contract.text(collection, r'[a-z0-9][a-z0-9_-]{0,63}')
            rows = rows.filter(collection=collection)
        rows = list(rows[:size+1])
        mirror = describe(MirrorRole.objects.select_related('host').get(host_id=host))
        return response(dict(version=1, mirror=mirror, snapshot=str(snapshot), observed_at=observation.observed_at,
            items=[row.metadata for row in rows[:size]], next_cursor=rows[size-1].position if len(rows)>size else None))
    except Observation.DoesNotExist:
        return response({'detail': 'Snapshot expired; refresh mirrors'}, 409)
    except (ValueError, KeyError, TypeError, MirrorRole.DoesNotExist):
        return response({'detail': 'Invalid archive query'}, 400)
