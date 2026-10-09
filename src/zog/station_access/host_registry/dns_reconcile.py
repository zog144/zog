"""Single central DNS writer. Registry intent and network-register state are both durable."""
import fcntl
import ipaddress
import json
import re
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from zog.network_register.client import Client, CloudflareError, credentials
from zog.network_register.dns import DnsRecords, DnsConflict
from .models import Host, InventoryScan, DnsAssignment

LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')


def configuration():
    path = getattr(settings, 'HOST_DNS_CONFIGURATION', '')
    if not path:
        return None
    config = json.loads(Path(path).read_text())
    domain, suffix = config['domain'], config['suffix']
    if not suffix.endswith('.' + domain) or len(suffix) > 189 or any(not LABEL.fullmatch(p) for p in suffix.split('.')):
        raise ValueError('Invalid DNS domain or suffix')
    if not Path(config['state_directory']).is_absolute():
        raise ValueError('DNS state directory must be absolute')
    return config


@contextmanager
def controller_lock(config, *, modes=('legacy',)):
    from .dns_cutover import controller_state
    # Never recreate missing controller state: loss needs explicit operator recovery.
    root = Path(config['state_directory'])
    if not root.is_dir() or not (root / 'network-register').is_dir():
        raise OSError('DNS provider state missing; restore it before continuing')
    with (root / 'controller.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Check AFTER acquiring the lock: never use a pre-cutover mode snapshot.
        if controller_state(config)['writer'] not in modes:
            raise ValueError('DNS writer is frozen or not authorized for this operation')
        yield root



def recent(stamp, now, seconds=600):
    return bool(stamp and 0 <= (now-stamp).total_seconds() <= seconds)


def desired(host, enabled, now):
    if not enabled:
        return 'absent', '', 'Publication disabled by operator'
    if not host.identities.filter(status='approved').exists():
        if host.identities.filter(status='revoked').exists():
            return 'absent', '', 'Host key explicitly revoked'
        return 'waiting', '', 'Migration hold: explicit key approval required; existing record retained'
    if host.provider != 'aws':
        return 'waiting', '', 'Only verified AWS hosts are supported in this pass'
    scans = {s.scope:s for s in InventoryScan.objects.filter(scope__in=['region-discovery',host.account_id+'/'+host.region])}
    if len(scans) != 2 or any(s.error or not recent(s.last_success,now) for s in scans.values()):
        return 'waiting', '', 'Waiting for successful, recent AWS inventory'
    if not recent(host.aws_checked_at,now) or host.aws_missing_since:
        return 'waiting', '', 'AWS observation stale or host missing; no DNS changes'
    state = host.aws_observation.get('state')
    if state in ('stopped','terminated'):
        return 'absent', '', 'AWS confirmed '+state
    if state != 'running':
        return 'waiting', '', 'Waiting for a confirmed running, stopped or terminated AWS state'
    if not recent(host.signed_last_received,now,180):
        return 'waiting', '', 'Waiting for an authenticated recent heartbeat'
    identity = {'account_id':host.account_id,'region':host.region,'instance_id':host.instance_id}
    if host.report.get('cloud') != identity:
        return 'waiting', '', 'Reported cloud identity does not match enrollment'
    try:
        address = ipaddress.IPv4Address(host.aws_observation.get('public_ip',''))
        if not address.is_global: raise ValueError('Nonpublic address')
    except ValueError:
        return 'waiting', '', 'AWS has no verified public IPv4 address'
    if host.report.get('public_ip') != str(address):
        return 'waiting', '', 'Reported address and AWS inventory disagree'
    return 'present', str(address), ''


from .identity import locked

@locked()
def reserve(host, config, label=None):
    """Caller holds controller lock; names and owners are immutable after reservation."""
    if Host.objects.get(pk=host.pk).archived_at:raise ValueError('Restore archived host before reserving DNS')
    existing = DnsAssignment.objects.filter(host=host).first()
    if existing:
        if label is not None and existing.name != label+'.'+config['suffix']:
            raise ValueError('DNS name is reserved; changing the display label does not rename it')
        return existing
    proposed = label if label is not None else (slugify(host.label)[:63].strip('-') or 'host-'+host.id.hex[:12])
    if not LABEL.fullmatch(proposed):
        raise ValueError('Use a DNS label of 1–63 lowercase letters, digits or internal hyphens')
    name = proposed+'.'+config['suffix']
    if DnsAssignment.objects.filter(name=name).exists():
        if label is not None: raise ValueError('DNS name is already reserved')
        proposed = proposed[:30].rstrip('-')+'-'+host.id.hex
        name = proposed+'.'+config['suffix']
    return DnsAssignment.objects.create(host=host,name=name,owner_id='host-discover:'+str(host.id))


def configure_assignment(host, config, enabled, label=None):
    from .identity import locked
    with controller_lock(config,modes=('legacy','shared')), locked():
        from .dns_cutover import controller_state, load_review
        if controller_state(config)['writer']=='shared':
            state=controller_state(config)
            reviewed=load_review(Path(config['state_directory']),state['review_id'])
            from .dns_membership import membership
            from zog.network_register.store import SqliteStateStore
            members=membership(SqliteStateStore(Path(config['state_directory'])/('dns-ledger-'+state['review_id']+'.sqlite3')),reviewed)
            if members['pending']:raise ValueError('A DNS membership change needs completion')
            if str(host.pk) not in members['host_ids']:
                raise ValueError('Host is outside the reviewed shared DNS selection')
        assignment = reserve(host,config,label)
        if assignment.enabled != enabled:
            assignment.enabled=enabled
            assignment.revision+=1
        assignment.status='pending'
        assignment.next_attempt=None
        assignment.error=''
        assignment.error_code=''
        assignment.save()
        return assignment


def serialize_assignment(assignment):
    fields=['name','enabled','revision','desired_action','desired_address','applied_revision','status',
            'record_id','observed_address','last_attempt','last_success','last_change','next_attempt','error_code','error','last_action']
    return {field:getattr(assignment,field) for field in fields}


def reconcile_one(assignment, dns, now):
    host = Host.objects.get(pk=assignment.host_id)
    action,address,reason = desired(host,assignment.enabled,now)
    changed = (action,address) != (assignment.desired_action,assignment.desired_address)
    if changed:
        assignment.revision+=1
        assignment.desired_action=action
        assignment.desired_address=address
        assignment.next_attempt=None
        assignment.failure_count=0
    if action == 'waiting':
        assignment.status='waiting_verification'
        assignment.error_code='verification'
        assignment.error=reason
        assignment.save()
        return 'waiting'
    if assignment.next_attempt and assignment.next_attempt > now:
        return 'backoff'
    # Commit intent BEFORE any provider operation. No transaction spans network I/O.
    assignment.status='applying'
    assignment.last_attempt=now
    assignment.error=''
    assignment.error_code=''
    assignment.save()
    try:
        if action == 'present':
            result=dns.ensure_a(assignment.name,address,assignment.owner_id,ttl=60)
        else:
            result=dns.remove_a(assignment.name,assignment.owner_id)
    except (DnsConflict,CloudflareError,ValueError,OSError) as error:
        assignment.failure_count+=1
        assignment.next_attempt=now+timedelta(seconds=min(1800,60*2**min(assignment.failure_count-1,5)))
        assignment.error_code=type(error).__name__
        assignment.status='conflict' if isinstance(error,DnsConflict) else 'storage_error' if isinstance(error,OSError) else 'provider_error'
        assignment.error=(str(error) if isinstance(error,(DnsConflict,CloudflareError,ValueError)) else 'Local DNS state unavailable; outcome may be uncertain. Restore storage before retrying.')[:1000]
        assignment.save()
        if isinstance(error,OSError): raise
        return assignment.status
    assignment.last_action=result['action']
    assignment.record_id=(result['record'] or {}).get('id','')
    assignment.observed_address=(result['record'] or {}).get('content','')
    assignment.applied_revision=assignment.revision
    assignment.last_success=timezone.now()
    if result['action'] in ('created','updated','deleted'):
        assignment.last_change=assignment.last_success
    assignment.status='synchronized' if action=='present' else 'unpublished'
    assignment.error=''
    assignment.error_code=''
    assignment.next_attempt=None
    assignment.failure_count=0
    assignment.save()
    return result['action']


def reconcile(config=None, dns=None, *, resource_ids=None):
    config=config or configuration()
    if not config: raise ValueError('DNS reconciliation is not configured')
    with controller_lock(config,modes=('legacy','shared')) as root:
        from .dns_cutover import controller_state
        if controller_state(config)['writer']=='shared':
            if dns is not None:raise ValueError('Legacy provider override prohibited after cutover')
            from .dns_shared import reconcile_locked
            result=reconcile_locked(config,root,resource_ids=resource_ids)
            from .dns_destinations import reconcile_all
            for key,count in reconcile_all(config,root,resource_ids=resource_ids).items():result[key]=result.get(key,0)+count
            return result
        if resource_ids is not None:raise ValueError('Single-host evaluation requires the shared writer')
        if dns is None:
            from .setup_configuration import cloudflare_credentials
            account,token=cloudflare_credentials(config)
            if account != config['account_id']: raise ValueError('Cloudflare account differs from controller binding')
            dns=DnsRecords(Client(account,token),config['domain'],root/'network-register')
        if config.get('auto_publish_enrolled',False):
            for host in Host.objects.filter(provider='aws',archived_at__isnull=True,identities__status='approved'):
                if desired(host,True,timezone.now())[0]=='present': reserve(host,config)
        outcomes={}
        for assignment in DnsAssignment.objects.order_by('name'):
            if not assignment.name.endswith('.'+config['suffix']):
                raise ValueError('Assignment outside configured DNS suffix')
            outcome=reconcile_one(assignment,dns,timezone.now())
            outcomes[outcome]=outcomes.get(outcome,0)+1
        return outcomes
