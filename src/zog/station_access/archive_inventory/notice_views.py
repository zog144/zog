"""Authenticated push only. Never resolve or fetch a producer/client URL."""
import json
import uuid
from django.db.models import Sum
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from zog.archive_mirror import notice_contract as c
from zog.host_identify import signatures
from zog.station_access.host_registry import identity
from zog.station_access.host_registry.models import HostIdentity, MirrorRole
from zog.station_access.host_registry.views import administrator
from .models import Entry, Observation, NoticeBundle
from .views import response

MAX_HOST_BYTES = 64 * 1024 * 1024


def missing(host_id, items):
    result = []
    for row in items:
        summary = row.get('licenses', {})
        if summary.get('state') == 'available' and not NoticeBundle.objects.filter(host_id=host_id, collection=row['collection'], digest=row['digest'], bundle_digest=summary['bundle_digest']).exists():
            result.append(dict(collection=row['collection'], digest=row['digest'], bundle_digest=summary['bundle_digest']))
    return result


@csrf_exempt
@require_POST
def ingest(request, host_id):
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > c.MAX_BUNDLE or len(request.body) > c.MAX_BUNDLE:
            return response({'detail': 'Notice evidence too large'}, 413)
        value = c.decode(request.body)
        fingerprint = request.headers.get('X-Host-Key', '')
        initial = HostIdentity.objects.filter(pk=fingerprint, host_id=host_id, status='approved', host__archived_at__isnull=True).first()
        if not initial:
            return response({'detail': 'Host authorization denied'}, 401)
        nonce, expiry = identity.proof(request, signatures.public_key(initial.public_key), str(host_id))
        with identity.locked():
            current = HostIdentity.objects.select_related('host').get(pk=fingerprint, host_id=host_id, status='approved', public_key=initial.public_key, host__archived_at__isnull=True)
            identity.consume(fingerprint, nonce, expiry)
            role = MirrorRole.objects.get(host=current.host)
            # Require a bounded, current signed observation for this exact binding.
            from django.utils import timezone
            from datetime import timedelta
            entries = Entry.objects.filter(observation__host=current.host, observation__role_revision=role.revision,
                observation__observed_at__gte=timezone.now()-timedelta(seconds=300),
                collection=value['collection'], digest=value['archive_digest']).order_by('-observation__observed_at')
            entry = entries.first()
            summary = c.summary(value)
            if not entry or entry.metadata.get('licenses') != summary or entry.metadata['kind'] != value['artifact_kind']:
                raise ValueError('Unobserved notice')
            existing = NoticeBundle.objects.filter(host=current.host, collection=value['collection'], digest=value['archive_digest']).first()
            if existing:
                if existing.bundle_digest != summary['bundle_digest'] or existing.evidence != value:
                    return response({'detail': 'Conflicting immutable notice evidence'}, 409)
            else:
                rows = NoticeBundle.objects.filter(host=current.host)
                size = len(c.canonical(value))
                if rows.count() >= 10000 or (rows.aggregate(size=Sum('size'))['size'] or 0)+size > MAX_HOST_BYTES:
                    return response({'detail': 'Notice cache capacity exceeded'}, 413)
                NoticeBundle.objects.create(host=current.host, collection=value['collection'], digest=value['archive_digest'], bundle_digest=summary['bundle_digest'], size=size, evidence=value)
        return response({'accepted': True})
    except Exception:
        return response({'detail': 'Invalid or unauthorized notice evidence'}, 400)


@never_cache
@require_GET
@administrator
def detail(request):
    try:
        if set(request.GET)-{'mirror', 'snapshot', 'collection', 'digest', 'offset', 'limit', 'format'} or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
            raise ValueError('Invalid query')
        host, snapshot = uuid.UUID(request.GET['mirror']), uuid.UUID(request.GET['snapshot'])
        c.pattern(request.GET['collection'], r'[a-z0-9][a-z0-9_-]{0,63}'); c.pattern(request.GET['digest'], c.HEX)
        row = Entry.objects.get(observation_id=snapshot, observation__host_id=host, observation__complete=True,
            observation__status='ok', collection=request.GET['collection'], digest=request.GET['digest'])
        summary = row.metadata.get('licenses', c.unavailable())
        if summary['state'] != 'available':
            return response({'detail': 'License information unavailable'}, 404)
        stored = NoticeBundle.objects.filter(host_id=host, collection=row.collection, digest=row.digest, bundle_digest=summary['bundle_digest']).first()
        if not stored:
            return response({'detail': 'Notice evidence has not been received'}, 404)
        value = c.validate(stored.evidence)
        if c.summary(value) != summary:
            return response({'detail': 'Notice evidence verification failed'}, 409)
        form = request.GET.get('format', 'metadata')
        if form == 'text':
            result = HttpResponse(c.document(value), content_type='text/plain; charset=utf-8')
            result['Content-Disposition'] = 'attachment; filename="notices-' + row.digest + '.txt"'
            result['Content-Security-Policy'] = "default-src 'none'; sandbox"
            result['Cache-Control'] = 'no-store'; result['X-Content-Type-Options'] = 'nosniff'
            return result
        if form != 'metadata':
            raise ValueError('Invalid format')
        offset, limit = int(request.GET.get('offset', 0)), int(request.GET.get('limit', 25))
        if not 0 <= offset <= c.MAX_RECORDS or not 1 <= limit <= 25:
            raise ValueError('Invalid pagination')
        return response(dict(schema=1, summary=summary, generation=value['generation'], source_identity=value['source_identity'],
            records=value['records'][offset:offset+limit], next_offset=offset+limit if offset+limit < len(value['records']) else None))
    except Entry.DoesNotExist:
        return response({'detail': 'Archive snapshot unavailable; refresh observations'}, 409)
    except (ValueError, KeyError, TypeError):
        return response({'detail': 'Invalid notice query'}, 400)
