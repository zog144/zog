"""Administrator role intent; heartbeat acknowledgement is not serving readiness."""
import time
from django.conf import settings
from django.utils import timezone
from zog.host_identify.signatures import origin
from .models import Host, MirrorRole
from .identity import locked, audit

STATES={'received','blocked','starting','running','ready','stopping','stopped','failed'}
REASONS={'','application-missing','runtime-unavailable','bridge-unconfigured','lease-expired','probe-failed','runtime-failed','identity-unapproved','configuration-invalid','operation-pending','lease-withdrawn','state-unavailable','start-uncertain'}


def assign(actor,host_id,selected,endpoint,expected_revision):
    if type(selected) is not bool or type(expected_revision) is not int:raise ValueError('Invalid role choice')
    if selected:
        endpoint=origin(endpoint)
        if len(endpoint)>253:raise ValueError('Endpoint too long')
    with locked():
        host=Host.objects.get(pk=host_id)
        if host.archived_at:raise ValueError('Restore archived host first')
        row=MirrorRole.objects.filter(host=host).first()
        if expected_revision != (row.revision if row else 0):raise ValueError('Role changed; refresh before saving')
        if selected and not host.identities.filter(status='approved').exists():raise ValueError('Approve host identity first')
        if selected and MirrorRole.objects.filter(selected=True).exclude(host=host).count()>=settings.HOST_MIRROR_LIMIT:raise ValueError('Mirror capacity reached')
        if selected and MirrorRole.objects.filter(selected=True,endpoint=endpoint).exclude(host=host).exists():raise ValueError('Endpoint already assigned')
        if row and row.selected==selected and (not selected or row.endpoint==endpoint):return row
        revision=row.revision+1 if row else 1
        row,_=MirrorRole.objects.update_or_create(host=host,defaults={'selected':selected,'endpoint':endpoint if selected else (row.endpoint if row else ''),
            'revision':revision,'changed_at':timezone.now(),'reported_state':'assigned' if selected else 'stopping',
            'reason':'','last_ready_at':None})
        audit(actor,'assign-mirror' if selected else 'remove-mirror',host=host,revision=revision,endpoint=row.endpoint,retain_archives=True)
        return row


def validate_status(value):
    if not isinstance(value,dict) or set(value)!={'revision','state','reason','runtime_id'}:raise ValueError('Invalid role report')
    if type(value['revision']) is not int or not 0<=value['revision']<=2**53-1 or value['state'] not in STATES or value['reason'] not in REASONS:
        raise ValueError('Invalid role report')
    if not isinstance(value['runtime_id'],str) or len(value['runtime_id'])>120:raise ValueError('Invalid runtime identity')
    if value['state'] in {'running','ready'} and not value['runtime_id']:raise ValueError('Runtime identity required')


def record(host,value):
    validate_status(value)
    role=MirrorRole.objects.filter(host=host).first()
    if not role or value['revision']!=role.revision:return
    if not role.selected and value['state']=='ready':return
    role.acknowledged_revision=value['revision'];role.reported_state=value['state'];role.reason=value['reason']
    role.runtime_id=value['runtime_id'];role.observed_at=timezone.now()
    if role.selected and value['state']=='ready':role.last_ready_at=role.observed_at
    role.save()


def serialize(host,now=None):
    now=now or timezone.now();r=MirrorRole.objects.filter(host=host).first()
    if not r:return {'selected':False,'revision':0,'endpoint':'','state':'unassigned','ready':False,'reason':'','acknowledged_revision':0,'observed_at':None}
    approved=host.identities.filter(status='approved').exists()
    fresh=bool(r.observed_at and 0<=(now-r.observed_at).total_seconds()<=180 and host.signed_last_received and (now-host.signed_last_received).total_seconds()<=180)
    state=r.reported_state if fresh and r.acknowledged_revision==r.revision else ('assigned' if r.selected else 'stopping')
    if not approved:state='blocked'
    return {'selected':r.selected,'revision':r.revision,'endpoint':r.endpoint,'state':state,
            'ready':bool(r.selected and approved and fresh and state=='ready'), 'reason':r.reason if approved else 'identity-unapproved',
            'acknowledged_revision':r.acknowledged_revision,'observed_at':r.observed_at,'last_ready_at':r.last_ready_at,
            'runtime_id':r.runtime_id,'stale':not fresh}


def response(host):
    row=MirrorRole.objects.filter(host=host).first()
    desired={'version':1,'revision':row.revision if row else 0,'selected':bool(row and row.selected),
             'endpoint':row.endpoint if row and row.selected else '', 'retain_archives':True,
             'lease_expires_at':int(time.time())+settings.HOST_ROLE_LEASE_SECONDS}
    candidates=[]
    for role in MirrorRole.objects.filter(selected=True,host__identities__status='approved').select_related('host').order_by('host_id'):
        state=serialize(role.host)
        candidates.append({'host_id':str(role.host_id),'endpoint':role.endpoint,'revision':role.revision,'ready':state['ready'],'state':state['state']})
    return {'desired':desired,'candidates':candidates}
