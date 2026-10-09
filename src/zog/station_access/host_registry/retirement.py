"""Reversible archival only: no cloud, DNS, credential or key mutations."""
import hashlib
import json
from datetime import timedelta
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from .models import Host, StationCredential, MirrorRole, ArchivePolicy, DnsAssignment, AdditionalDnsAssignment, EnrollmentRequest
from .identity import locked, audit
from .matching import summary, cloud_identity


def host_generation_preview(host):
    value = host.report.get('host_generation') if isinstance(host.report, dict) else None
    if not isinstance(value, dict):
        return None
    try:
        from zog.station_access.archive_inventory.generation_resolution import resolve_generation
        slots = {}
        for slot in ('HOST-A', 'HOST-B'):
            row = value['slots'][slot]
            if row is None:
                slots[slot] = None
                continue
            resolution = resolve_generation(row['generation'])
            slots[slot] = {
                'generation': row['generation'],
                'root_partuuid': row['root_partuuid'],
                'resolution': resolution['state'],
                'digest': resolution['digest'],
                'candidate_count': resolution['candidate_count'],
                'archive': resolution['observation'],
            }
        return {
            'schema': value['schema'],
            'source': value['source'],
            'installation': value['installation'],
            'selected_slot': value['selected_slot'],
            'booted_slot': value['booted_slot'],
            'slots': slots,
            'transitional_boot_bundle': value['transitional_boot_bundle'],
            'received_at': host.last_received,
        }
    except (KeyError, TypeError, ValueError):
        return {'state': 'invalid-retained-evidence', 'received_at': host.last_received}


class RemovalConflict(ValueError):
    pass


def preview(host):
    now = timezone.now()
    keys = list(host.identities.values('fingerprint','status','approved_by','approved_at','revoked_at'))
    credential = StationCredential.objects.filter(host=host).values('revision','received_at','source_fingerprint').first()
    role = MirrorRole.objects.filter(host=host).values('selected','endpoint','revision','acknowledged_revision','reported_state','runtime_id').first()
    policy = ArchivePolicy.objects.filter(host=host).values('operations','collections').first()
    dns = list(DnsAssignment.objects.filter(host=host).values('name','enabled','status','record_id'))
    dns += list(AdditionalDnsAssignment.objects.filter(host=host).values('name','enabled','status','record_id'))
    pending = list(EnrollmentRequest.objects.filter(claimed_host_id=str(host.pk),status='pending',expires_at__gt=now).values_list('fingerprint',flat=True))
    blockers = []
    if host.deployment_jobs.filter(state__in=('queued','submitting','running','uncertain')).exists():
        blockers.append('Resolve the outstanding deployment job before archival.')
    if any(key['status']=='approved' for key in keys):blockers.append('Explicitly revoke the approved identity before archival; stop or reconfigure its beaconer separately.')
    legacy = bool(host.token_digest and not host.token_revoked)
    if legacy:blockers.append('Explicitly revoke the legacy credential before archival.')
    if credential:blockers.append('Withdraw the stored station login credential through the signed beacon workflow before archival.')
    if policy and policy['operations'] and policy['collections']:blockers.append('Withdraw archive permissions before archival.')
    # Conservative expiry bound also covers tokens issued before archival was introduced.
    times = [key['revoked_at'] for key in keys if key['revoked_at']]
    if keys and host.last_received:times.append(host.last_received)
    until = max(times)+timedelta(seconds=905) if times else None
    if until and until > now:blockers.append('Previously issued archive tokens may remain valid; wait until '+until.isoformat()+' (15 minutes plus 5 seconds).')
    if role and (role['selected'] or role['reported_state']!='stopped' or role['acknowledged_revision']!=role['revision']):
        blockers.append('Remove the mirror role explicitly and obtain acknowledgement that the current revision is stopped; retained archives are not deleted.')
    if dns:blockers.append('A managed DNS assignment or name reservation still exists. Resolve its ownership explicitly before archival; disabling publication alone retains the reservation.')
    if pending:blockers.append('Reject or resolve pending migration requests claiming this record before archival.')
    value = {'host': summary(host), 'archived_at':host.archived_at,'archived_by':host.archived_by,
             'identities':keys,'station_credential':credential,'legacy_credential_active':legacy,
             'archive_policy':policy,'possible_token_expiry':until,'mirror_role':role,'dns':dns,
             'pending_fingerprints':pending,'blockers':blockers,
             'explanation':'Archival hides a command-center record; it does not stop or terminate EC2, stop a beaconer, revoke credentials, move keys, or delete DNS. History is retained. AWS refreshes update this same archived record. Archival is not an enrollment ban: a matching request requires explicit restoration and fingerprint approval; an unrelated new identity can still request enrollment.'}
    value['revision'] = hashlib.sha256(json.dumps(value,sort_keys=True,cls=DjangoJSONEncoder).encode()).hexdigest()
    value['host_generation'] = host_generation_preview(host)
    value['can_archive'] = not blockers and not host.archived_at
    return value


def archive_host(actor, host_id, expected):
    with locked():
        host=Host.objects.get(pk=host_id)
        current=preview(host)
        if current['revision']!=expected:raise RemovalConflict('Host or dependencies changed. Reload the removal preview before confirming.')
        if not current['can_archive']:raise RemovalConflict('Archival is blocked. Resolve the dependencies shown in the preview.')
        host.archived_at=timezone.now();host.archived_by=actor
        host.save(update_fields=['archived_at','archived_by'])
        audit(actor,'archive-host',host=host,preview_revision=expected,label=host.label,
              provider=host.provider,account_id=host.account_id,region=host.region,instance_id=host.instance_id)
        return host


def restore_host(actor,host_id,expected):
    with locked():
        host=Host.objects.get(pk=host_id)
        if preview(host)['revision']!=expected:raise RemovalConflict('Record changed. Reload the preview.')
        if not host.archived_at:raise RemovalConflict('Record is not archived')
        host.archived_at=None;host.archived_by='';host.save(update_fields=['archived_at','archived_by'])
        audit(actor,'restore-host',host=host)
        return host


def duplicate_candidates(hosts):
    """Review hints only; hostname equality must never select enrollment or remove data."""
    by_hostname={};by_cloud={}
    for host in hosts:
        names={host.report.get('hostname'),host.label,host.aws_observation.get('private_dns'),host.aws_observation.get('public_dns')}
        for name in names:
            if name:by_hostname.setdefault(name,[]).append(host)
        if host.provider=='aws':by_cloud.setdefault((host.account_id,host.region,host.instance_id),[]).append(host)
    result={}
    for host in hosts:
        if host.provider!='generic' or host.archived_at:continue
        candidates={other.pk:other for name in {host.report.get('hostname'),host.label} if name for other in by_hostname.get(name,[]) if other.pk!=host.pk}
        try:cloud=cloud_identity(host.report)
        except ValueError:cloud=None
        if cloud:
            for other in by_cloud.get((cloud['account_id'],cloud['region'],cloud['instance_id']),[]):
                if other.pk!=host.pk:candidates[other.pk]=other
        if candidates:result[str(host.pk)]=[summary(other) for other in candidates.values()]
    return result
