"""Explicit, bounded deployment jobs. Web requests never execute remote commands."""
import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4
from django.conf import settings
from django.utils import timezone
from .identity import locked, audit
from .models import DeploymentJob, Host
from .setup_configuration import export_destinations

BUSY = ('queued', 'submitting', 'running', 'uncertain')


def enabled():
    return getattr(settings, 'HOST_DEPLOY_JOBS_ENABLED', False)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def target(host):
    identity = host.identities.filter(status='approved').first()
    if host.archived_at or host.provider != 'aws' or not identity or not all((host.account_id,host.region,host.instance_id,host.workspace_id)):
        raise ValueError('Choose an enrolled, unarchived AWS host with an approved identity and deployment workspace.')
    return dict(host_id=str(host.pk), account_id=host.account_id, region=host.region,
                instance_id=host.instance_id, workspace_id=host.workspace_id, fingerprint=identity.fingerprint)


def require_enabled():
    if not enabled(): raise ValueError('Deployment worker is not enabled on this station.')


def idle(host, excluding=None):
    if host.deployment_jobs.filter(state__in=BUSY).exclude(pk=excluding).exists():
        raise ValueError('Resolve the existing host job before starting another operation.')


def create_inspection(actor, host_id, action_id):
    require_enabled()
    identifier = UUID(action_id)
    with locked():
        host = Host.objects.get(pk=host_id)
        existing = DeploymentJob.objects.filter(pk=identifier).first()
        if existing:
            if existing.host_id != host.pk or existing.operation != 'inspect': raise ValueError('Action identity conflicts with another job.')
            return existing
        selected = target(host);idle(host)
        job = DeploymentJob.objects.create(id=identifier, host=host, actor=actor, operation='inspect',
                                          request={'id':str(identifier),'action':'inspect','target':selected})
        audit(actor,'deployment-inspect-queued',job_id=str(job.pk),host_id=str(host.pk))
        return job


def preview(actor, host_id, inspection_id):
    require_enabled()
    with locked():
        host = Host.objects.get(pk=host_id);selected = target(host);idle(host)
        inspection = DeploymentJob.objects.get(pk=inspection_id,host=host,operation='inspect',state='succeeded')
        if not inspection.finished_at or inspection.finished_at < timezone.now()-timedelta(minutes=5) or inspection.request['target'] != selected:
            raise ValueError('Inspect this host again before reviewing changes.')
        observation=inspection.result.get('observation',{})
        if not observation.get('apply_supported'): raise ValueError('This host does not have a supported active destination-file installation.')
        destinations=export_destinations()
        if not any(row['enabled'] and row['server']==observation.get('primary') for row in destinations['destinations']):
            raise ValueError('Keep this host’s existing primary registry enabled in the saved list.')
        job=DeploymentJob.objects.create(host=host,actor=actor,operation='apply',state='review',expires_at=timezone.now()+timedelta(minutes=5))
        job.request=dict(id=str(job.pk),action='apply',target=selected,expected_sha256=observation['destinations_sha256'],destinations=destinations)
        job.result={'before':observation['destinations'],'primary':observation['primary']}
        job.save()
        audit(actor,'deployment-review-created',job_id=str(job.pk),host_id=str(host.pk))
        return job


def confirm(actor, identifier):
    require_enabled()
    with locked():
        job=DeploymentJob.objects.select_related('host').get(pk=identifier)
        if job.operation!='apply': raise ValueError('Only destination changes require confirmation.')
        if job.state!='review': return job  # duplicate confirmation never dispatches twice
        if job.expires_at < timezone.now() or target(job.host)!=job.request['target'] or fingerprint(export_destinations())!=fingerprint(job.request['destinations']):
            raise ValueError('The review is stale. Inspect and review the current configuration again.')
        idle(job.host,job.pk)
        job.state='queued';job.actor=actor;job.save(update_fields=['state','actor'])
        audit(actor,'deployment-apply-confirmed',job_id=str(job.pk),host_id=str(job.host_id))
        return job


def recover(actor, identifier):
    require_enabled()
    with locked():
        job=DeploymentJob.objects.select_related('host').get(pk=identifier)
        if job.state!='uncertain': return job
        if job.operation=='inspect':
            job.state='failed';job.message='Inspection was interrupted. Start a new inspection.';job.finished_at=timezone.now()
        else:
            if target(job.host)!=job.request['target']: raise ValueError('The host binding changed; operator recovery is required.')
            job.checking_outcome=True;job.command_id='';job.state='queued';job.finished_at=None
        job.save()
        audit(actor,'deployment-outcome-check',job_id=str(job.pk),host_id=str(job.host_id))
        return job


def gateway(target):
    from zog.host_deploy.station import StationDeployment
    return StationDeployment(target)


def process(identifier):
    """One bounded worker tick. No auto-resubmission after a lost send reply."""
    require_enabled()
    with locked():
        job=DeploymentJob.objects.select_related('host').get(pk=identifier)
        if job.state=='submitting':
            if job.started_at and job.started_at < timezone.now()-timedelta(minutes=2):
                job.state='uncertain';job.message='Submission was interrupted; check the original outcome.';job.save()
            return
        if job.state not in ('queued','running'): return
        submit=job.state=='queued'
        if submit:
            try:
                if target(job.host)!=job.request['target']: raise ValueError()
                if job.operation=='apply' and not job.checking_outcome:
                    if job.expires_at < timezone.now() or fingerprint(export_destinations())!=fingerprint(job.request['destinations']): raise ValueError()
            except Exception:
                job.state='uncertain' if job.checking_outcome else 'failed';job.message='Host binding or saved destinations changed before execution.';job.finished_at=timezone.now();job.save();return
            job.state='submitting';job.attempt_id=uuid4();job.started_at=timezone.now();job.save()
    try:
        adapter=gateway(job.request['target'])
        if submit:
            request=dict(job.request,action='recover' if job.checking_outcome else job.request['action'])
            command_id=adapter.submit(request)
            DeploymentJob.objects.filter(pk=job.pk,state='submitting',attempt_id=job.attempt_id).update(state='running',command_id=command_id,command_ids=[*job.command_ids,command_id][-25:])
            return
        result=adapter.poll(job.command_id,str(job.pk))
        if result is None:
            if job.started_at < timezone.now()-timedelta(minutes=3):
                DeploymentJob.objects.filter(pk=job.pk,state='running',attempt_id=job.attempt_id).update(state='uncertain',message='Remote completion is not yet verified. Check the outcome.')
            return
        status=result.get('status')
        # Do not forward raw remote stdout, stderr or unexpected response fields.
        if status=='inspected' and job.operation=='inspect':
            result={'observation':safe_observation(result['observation'])};state='succeeded';message='Read-only inspection complete.'
        elif status=='installed' and job.operation=='apply':
            expected=hashlib.sha256((json.dumps(job.request['destinations'],sort_keys=True,separators=(',', ':'),ensure_ascii=True)+'\n').encode()).hexdigest()
            if result.get('sha256')!=expected: raise ValueError('Installed digest mismatch')
            result={'sha256':expected};state='succeeded';message='Destination file verified installed. Beacon processing and registry approvals remain separate.'
        elif status=='blocked':
            result={};state='failed';message='Remote configuration changed or is unsupported. Inspect and review again.'
        elif status=='unavailable' and job.operation=='inspect':
            result={};state='failed';message='Host deployment could not be inspected. Check the worker permissions and beacon installation.'
        else:
            result={};state='uncertain';message='Outcome is unresolved. Check this job; do not submit a replacement.'
        DeploymentJob.objects.filter(pk=job.pk,state='running',attempt_id=job.attempt_id).update(state=state,result=result,message=message,finished_at=timezone.now())
    except Exception as error:
        try:
            from zog.host_deploy.station import NotSubmitted
        except ImportError:
            NotSubmitted = type('UnavailableTransport', (Exception,), {})
        definitely_not_sent=submit and isinstance(error,NotSubmitted) and not job.checking_outcome
        DeploymentJob.objects.filter(pk=job.pk,state__in=('submitting','running'),attempt_id=job.attempt_id).update(
            state='failed' if definitely_not_sent else 'uncertain',
            message='Target preflight failed before submission.' if definitely_not_sent else 'Worker could not verify the outcome. Check the original job.',finished_at=timezone.now())


def safe_observation(value):
    from .setup_configuration import origin
    if not isinstance(value,dict) or type(value.get('apply_supported')) is not bool: raise ValueError()
    primary=origin(value['primary'])
    sha=value.get('destinations_sha256')
    if sha is not None and (not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha)): raise ValueError()
    rows=[]
    if not isinstance(value.get('destinations'),list) or len(value['destinations'])>16: raise ValueError()
    for row in value['destinations']:
        ca = row.get('ca_sha256')
        if ca is not None and (not isinstance(ca,str) or len(ca)!=64 or any(c not in '0123456789abcdef' for c in ca)): raise ValueError()
        rows.append(dict(server=origin(row['server']),enabled=row['enabled'] is True,
                         label=str(row['label'])[:100],revision=int(row['revision']),ca_sha256=row.get('ca_sha256')))
    allowed_states={'active','inactive','failed','activating','deactivating','unknown'}
    result={k:value[k] if value.get(k) in allowed_states else 'unknown' for k in ('beacon_state','station_state')}
    import re
    result.update({k:value.get(k) if isinstance(value.get(k),str) and re.fullmatch(r'[A-Za-z0-9.+_-]{1,40}',value[k]) else None for k in ('beacon_version','station_version')})
    return dict(result,primary=primary,destinations_sha256=sha,destinations=rows,apply_supported=value['apply_supported'],
                reason='Ready to review destination changes.' if value['apply_supported'] else 'An active beacon using a valid destination file is required.')


def serialize(job):
    result=job.result
    return dict(id=str(job.pk),host_id=str(job.host_id),host_label=job.host.label,operation=job.operation,state=job.state,
        actor=job.actor,message=job.message,created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,finished_at=job.finished_at.isoformat() if job.finished_at else None,
        expires_at=job.expires_at.isoformat() if job.expires_at else None,result=result,
        target={k:job.request.get('target',{}).get(k) for k in ('account_id','region','instance_id')},
        destinations=[dict(label=r['label'],server=r['server'],enabled=r['enabled'],revision=r['revision'],custom_ca=bool(r['ca_certificate']),ca_sha256=hashlib.sha256(r['ca_certificate'].encode()).hexdigest() if r['ca_certificate'] else None) for r in job.request.get('destinations',{}).get('destinations',[])])
