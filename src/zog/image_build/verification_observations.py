"""Versioned named verification outcomes, separate from command/log ownership."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import ImageBuildError
from .filesystem import write_json
from .metadata import identity

SCHEMA = 'image-build-verification-observation-v1'


def observation(*, check_id, definition_digest, subject, attempt_id, sequence,
                outcome, execution, environment_digest, evidence):
    value = dict(schema=SCHEMA, check_id=check_id, definition_digest=definition_digest,
        subject=subject, attempt_id=attempt_id, sequence=sequence, outcome=outcome,
        execution=execution, environment_digest=environment_digest, evidence=evidence,
        granularity='command', timing={'started_at':None, 'finished_at':None, 'observed_at':None},
        producer={'name':'image-build', 'contract':SCHEMA})
    value['id'] = 'sha256:'+identity(value)
    validate(value)
    return value


def validate(value):
    fields={'schema','id','check_id','definition_digest','subject','attempt_id','sequence',
            'outcome','execution','environment_digest','evidence','granularity','timing','producer'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=SCHEMA:
        raise ImageBuildError('unsupported verification observation')
    if value['id']!='sha256:'+identity({k:v for k,v in value.items() if k!='id'}):
        raise ImageBuildError('verification observation identity differs')
    if value['outcome'] not in {'PASS','FAIL','ERROR','SKIP'}:
        raise ImageBuildError('invalid verification outcome')
    if type(value['sequence']) is not int or value['sequence']<0:
        raise ImageBuildError('invalid verification sequence')
    for key in ('check_id','attempt_id','definition_digest','environment_digest'):
        if not isinstance(value[key],str) or not value[key]:
            raise ImageBuildError('verification identity missing: '+key)
    if not isinstance(value['subject'],dict) or not value['subject'] or not value['evidence']:
        raise ImageBuildError('verification subject/evidence missing')
    return value


def capture(builder, folder, prepared, index, error=None):
    """Called after a named installed command. Never turn pending into a result."""
    binding=prepared['binding']
    if (not isinstance(binding,dict) or
            binding.get('verification_report_contract')!='image-build-installed-verification-v1'):
        return None
    p=builder.provenance
    if p is None:
        return None
    folder=Path(folder)
    checkpoint=folder/f'command-{index}.execution.json'
    if checkpoint.exists():
        raw=json.loads(checkpoint.read_text())
        request=raw.get('request',{})
        if (request.get('command')!=prepared['commands'][index] or
                request.get('root')!=str((folder/'root').resolve()) or
                raw.get('policy')!=builder._policy().get('controller')):
            raise ImageBuildError('verification completion binding differs')
        if raw.get('cleanup_complete') is not True or type(raw.get('exit_code')) is not int:
            return None
        outcome='PASS' if raw['exit_code']==0 else 'FAIL'
        execution={key:raw[key] for key in ('runtime_id','invocation_id','journal_reference','exit_code')}
    else:
        raw=getattr(error,'record',{})
        if raw.get('state')!='completed' or raw.get('outcome') not in {
                'nonzero-exit','signal','timeout','fault','cancelled'}:
            return None
        # Adapter has already bound the job request to this command checkpoint.
        controller=folder/f'command-{index}.controller.json'
        if not controller.exists():return None
        saved=json.loads(controller.read_text())
        if saved.get('job_id')!=raw.get('job_id') or saved.get('request_id')!=raw.get('request_id'):
            raise ImageBuildError('verification failure job identity differs')
        outcome='FAIL' if raw['outcome']=='nonzero-exit' else 'ERROR'
        execution={key:raw.get(key) for key in ('job_id','invocation_id','journal_reference','exit_code','outcome')}
    name=binding.get('verification_check','installed-trust')
    value=observation(check_id='image-build/'+name+'/command/'+str(index),
        definition_digest='sha256:'+identity(prepared['commands'][index]),
        subject={'kind':'generation-candidate', 'generation_id':json.dumps(
            [p.host_id,p.project_id,identity(binding)],separators=(',',':')),
            'root_inventory_digest':'sha256:'+identity(prepared['root'])},
        attempt_id=json.dumps([p.host_id,p.project_id,folder.name],separators=(',',':')),
        sequence=index, outcome=outcome, execution=dict(host_id=p.host_id,**execution),
        environment_digest='sha256:'+identity(builder._policy()),
        evidence=[{'kind':'execution-checkpoint','digest':'sha256:'+identity(raw)},
                  {'kind':'build-trace','host_id':p.host_id,'build_id':'attempt:'+folder.name}])
    # Freeze observation time before storing material: interrupted capture must
    # not silently receive a new timestamp or identity on recovery.
    intent=folder/'verification-observations'/f'{index}.prepared.json'
    if intent.exists():
        saved=json.loads(intent.read_text());validate(saved)
        comparable=dict(saved, timing=dict(saved['timing'],observed_at=None))
        comparable['id']='sha256:'+identity({k:v for k,v in comparable.items() if k!='id'})
        if comparable!=value:raise ImageBuildError('immutable verification observation changed')
        value=saved
    else:
        value['timing']['observed_at']=datetime.now(timezone.utc).isoformat()
        value['id']='sha256:'+identity({k:v for k,v in value.items() if k!='id'})
        write_json(intent,value)
    # Capture after execution, not a claim of pre-execution observation. Retain
    # bytes through the canonical artifact store without inventing record kinds.
    descriptor=p._bytes('verification-observation.json',value)
    path=folder/'verification-observations'/f'{index}.json'
    if path.exists() and json.loads(path.read_text())!=descriptor:
        raise ImageBuildError('immutable verification observation changed')
    write_json(path,descriptor)
    index_path=p.root/'observation-index'/('sha256-'+identity(binding))/(value['id'][7:]+'.json')
    write_json(index_path,descriptor)
    return descriptor
