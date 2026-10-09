"""Read-only producer export for build-record/build-trace integration consumers."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

from .errors import ImageBuildError
from .filesystem import inventory, write_json
from .metadata import identity
from . import artifact_observations, verification_observations as vo

SCHEMA='image-build-integration-observations-v1'


def artifact(p, descriptor):
    path=p.root/'artifacts'/descriptor['digest'][7:]
    if path.is_symlink():raise ImageBuildError('observation evidence symlink')
    raw=path.read_bytes()
    if len(raw)!=descriptor['size'] or 'sha256:'+hashlib.sha256(raw).hexdigest()!=descriptor['digest']:
        raise ImageBuildError('observation evidence digest differs')
    return raw


def record(bundle, key, kind):
    value=bundle['records'][key]
    if value['kind']!=kind:raise ImageBuildError('unexpected canonical record kind')
    return value['data']


def source_and_package_facts(p, bundle, members):
    sources=[];relationships=[];gaps=[]
    for name,member in sorted(members.items()):
        output=record(bundle,member['provenance']['output'],'package-output')
        if output['attempt'] is None:
            gaps.append({'package':name,'reason':'legacy-output-without-source-or-recipe'});continue
        start=record(bundle,output['attempt'],'attempt-start')
        inputs=record(bundle,start['inputs'],'build-inputs')
        recipe=json.loads(artifact(p,inputs['recipe']))
        files={f['name']:f for f in recipe['files']}
        def literal(name):
            return ast.literal_eval(artifact(p,files[name]).decode()) if name in files else None
        declarations=literal('package/source-provenance.py')
        source_specs=literal('package/sources.py') or []
        integration=literal('package/integration.py') or {}
        subject={'kind':'package','package':name,'output_record':member['provenance']['output']}
        dependencies=literal('package/dependencies.py')
        if dependencies is None:
            gaps.append({'package':name,'reason':'no-frozen-dependency-declaration'})
        elif not isinstance(dependencies,dict):
            raise ImageBuildError('invalid frozen dependency declaration')
        else:
            for phase in ('build','test','runtime'):
                for target in dependencies.get(phase,[]):
                    item=dict(subject=subject,relation='declares-'+phase+'-dependency',
                        target={'kind':'package','value':target},
                        evidence={'kind':'frozen-recipe','artifact':files['package/dependencies.py']})
                    item['id']='sha256:'+identity(item);relationships.append(item)
        for dependency in inputs['dependencies']:
            target=record(bundle,dependency['output'],'package-output')
            item=dict(subject=subject,relation='used-build-output',
                target={'kind':'package-output','value':dependency['output'],'package':target['package']},
                evidence={'kind':'canonical-build-inputs','record':start['inputs']})
            item['id']='sha256:'+identity(item);relationships.append(item)
        for source_id in inputs['sources']:
            selected=record(bundle,source_id,'source-selection')
            for archive in selected['archives']:
                matches=[s for s in source_specs if s['sha256']==archive['digest'][7:]
                         and s['destination']==archive['name']]
                upstream=[]
                if declarations:
                    for item in declarations['sources']:
                        if item['source'] in matches:upstream.extend(item['upstream'])
                value=dict(package=name,project=integration.get('project'),
                    output_record=member['provenance']['output'],build_inputs_record=start['inputs'],
                    source_selection_record=source_id,pin=selected['pin'],archive=archive,
                    downloads=matches,upstream=upstream or [dict(u,revision_type='git' if u['revision'] else 'unknown')
                                                          for u in selected['upstream']],
                    archive_revision_relationship='declared-not-independently-reproduced',
                    release_tags=[{'repository':u['repository'],'tag':u['revision']} for u in upstream if u['revision_type']=='tag'],gaps=bundle['records'][source_id]['gaps'])
                value['id']='sha256:'+identity(value);sources.append(value)
    return sources,relationships,gaps


def export_generation(p, selection, *, readelf='readelf'):
    """Inspect a verified generation. Does not alter old canonical records."""
    from .generation_provenance import verify
    bundle=verify(p,selection)
    pointer=selection.manifest['build_record']
    generation=record(bundle,pointer['record'],'generation')
    entries=inventory(selection.root)
    owners={}
    for name,member in selection.manifest['packages'].items():
        for entry in member['outputs']:
            if entry['kind']=='file':owners.setdefault((entry['path'],entry['sha256']),[]).append(name)
    owner_paths={entry['path']:sorted(owners.get((entry['path'],entry.get('sha256')),[])) for entry in entries}
    scanned=artifact_observations.scan(selection.root,entries,owner_paths,readelf=readelf)
    sources,relationships,gaps=source_and_package_facts(p,bundle,selection.manifest['packages'])
    results=[];checks=[]
    for descriptor in generation['verification']:
        report=json.loads(artifact(p,descriptor))
        if report.get('kind')!='image-build-installed-verification-v1':
            gaps.append({'reason':'unsupported-verification-report','artifact':descriptor});continue
        check_id='image-build/'+report['check']+'/command/0'
        owner=selection.manifest['inputs']
        definition='sha256:'+identity(['/bin/bash','-eu','-c',owner['verification_command']])
        checks.append({'check_id':check_id,'definition_digest':definition,'granularity':'command'})
        results.append(vo.observation(check_id=check_id,definition_digest=definition,
            subject={'kind':'generation-candidate','generation_id':generation['generation_id'],
                     'root_inventory_digest':report['root_inventory_digest']},
            attempt_id=json.dumps([p.host_id,p.project_id,report['trace']['build_id'].removeprefix('attempt:')],separators=(',',':')),
            sequence=0,outcome='PASS',execution=report['execution'],environment_digest=report['policy_digest'],
            evidence=[{'kind':'canonical-installed-report','artifact':descriptor},
                      {'kind':'canonical-generation','record':pointer['record']},
                      {'kind':'build-trace',**report['trace']}]))
    # Newly captured command outcomes are durable artifacts indexed by candidate
    # input identity. They may include failures for candidates never published.
    for descriptor in observation_descriptors(p,selection.generation):
        result=json.loads(artifact(p,descriptor));vo.validate(result)
        if result['subject'].get('generation_id')!=generation['generation_id']:
            raise ImageBuildError('verification observation generation differs')
        matches=[r for r in results if r['check_id']==result['check_id'] and
                 r['execution'].get('invocation_id')==result['execution'].get('invocation_id')]
        if matches and any(r['outcome']!=result['outcome'] for r in matches):
            raise ImageBuildError('verification observations conflict')
        results=[r for r in results if r not in matches]+[result]
    if not checks:gaps.append({'reason':'no-canonical-named-verification-report'})
    # Validate again after observation; a mutable/mismatched root is never exported.
    if inventory(selection.root)!=entries:raise ImageBuildError('generation changed during observation')
    value=dict(schema=SCHEMA,producer={'name':'image-build','contract':SCHEMA,
        'implementation_digest':'sha256:'+identity({f.name:hashlib.sha256(f.read_bytes()).hexdigest()
            for f in (Path(__file__),Path(vo.__file__),Path(artifact_observations.__file__))})},
        context={'generation_id':generation['generation_id'],'generation_record':pointer['record'],
                 'root_inventory_digest':'sha256:'+identity(entries)},
        verification={'checks':checks,'results':sorted(results,key=lambda r:r['id']),
                      'coverage':'named installed command checks only; no parsed upstream subtests'},
        relationships=sorted(relationships+scanned['relationships'],key=lambda r:r['id']),
        sources=sorted(sources,key=lambda r:r['id']),
        coverage=scanned['coverage'],gaps=gaps+scanned['issues'],
        derivation='post-build-inspection; does not retrofit canonical pre-execution evidence')
    value['id']='sha256:'+identity(value)
    return value


def observation_descriptors(p, generation):
    if len(generation)!=64 or any(c not in '0123456789abcdef' for c in generation):
        raise ImageBuildError('invalid generation identity')
    return [json.loads(f.read_text()) for f in sorted((p.root/'observation-index'/('sha256-'+generation)).glob('*.json'))]


def export_candidate(p, generation):
    """Named terminal results for candidates, including those never published."""
    results=[]
    expected=json.dumps([p.host_id,p.project_id,generation],separators=(',',':'))
    for descriptor in observation_descriptors(p,generation):
        value=json.loads(artifact(p,descriptor));vo.validate(value)
        if value['subject'].get('generation_id')!=expected:raise ImageBuildError('candidate scope differs')
        results.append(value)
    return {'schema':'image-build-candidate-verifications-v1','generation_id':expected,
            'results':results,'coverage':'captured terminal commands only; absence is not SKIP'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',required=True)
    parser.add_argument('--provenance-config',required=True,help='Frozen provenance configuration or owner intent JSON')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--selection');group.add_argument('--candidate')
    parser.add_argument('--output',required=True)
    parser.add_argument('--readelf',default='readelf')
    args=parser.parse_args()
    from .provenance import Provenance
    from .engine import read_selection
    configuration=json.loads(Path(args.provenance_config).read_text())
    p=Provenance.from_configuration(Path(args.state),configuration.get('provenance',configuration))
    value=export_generation(p,read_selection(args.selection),readelf=args.readelf) if args.selection else export_candidate(p,args.candidate)
    write_json(Path(args.output),value)


if __name__=='__main__':main()
