"""Reviewed package-stage graphs compiled to existing durable package pipelines."""
import argparse
import fcntl
import json
import logging
import platform
import shutil
import uuid
from pathlib import Path
from .engine import ImageBuild, read_selection
from .metadata import literal, names, relative, load_packages, order, identity
from .filesystem import digest, inventory, merge, sync_tree, write_json, ensure_directory, discard_staging
from .configuration import configured_runner
from .errors import ImageBuildError
from .developer.seed_build import verify


def stage_recipes(plan_path, catalogue, destination, *, pin_date=None):
    plan = literal(plan_path)
    if plan.get('schema') != 1 or plan.get('architecture') != platform.machine():
        raise ImageBuildError('unsupported stage plan or host architecture')
    entries = plan['stages']
    names([entry['id'] for entry in entries])
    catalogue, destination = Path(catalogue).resolve(), Path(destination)
    ensure_directory(destination)
    from .pins import snapshot, validate
    snapshot(catalogue, entries, destination, pin_date)
    for entry in entries:
        source = catalogue / relative(entry['recipe'])
        if not source.resolve().is_relative_to(catalogue):
            raise ImageBuildError('stage recipe escapes catalogue')
        license_path = source / 'license.py'
        if not license_path.exists(): license_path = catalogue / entry['project'] / 'license.py'
        from .licensing import load as load_license
        load_license(license_path)  # New materializations require an explicit record.
        from .source_provenance import NAME, load as load_source_provenance
        provenance_path = source / NAME
        if not provenance_path.exists() and not provenance_path.is_symlink():
            provenance_path = catalogue / entry['project'] / NAME
        has_provenance = provenance_path.exists() or provenance_path.is_symlink()
        if has_provenance:
            load_source_provenance(provenance_path, literal(source / 'sources.py'))
        expected = [r for r in inventory(source) if r['path'] not in ('license.py', NAME)]
        if has_provenance:
            expected.append({'kind':'file','mode':0o644,'path':NAME,'sha256':digest(provenance_path)})
        expected.append({'kind':'file','mode':0o644,'path':'license.py','sha256':digest(license_path)})
        expected.sort(key=lambda r:r['path'])
        target = destination / entry['id']
        if not target.exists():
            shutil.copytree(source, target)
            shutil.copyfile(license_path, target / "license.py")
            (target / "license.py").chmod(0o644)
            if has_provenance:
                shutil.copyfile(provenance_path, target / NAME)
                (target / NAME).chmod(0o644)
        elif expected != inventory(target):
            raise ImageBuildError('recorded stage recipe changed')
    packages = load_packages(destination)
    validate(destination, packages)
    if set(packages) != {entry['id'] for entry in entries}:
        raise ImageBuildError('stage snapshot has unexpected definitions')
    for entry in entries:
        metadata = packages[entry['id']].integration
        if metadata.get('project') != entry['project'] or metadata.get('stage_id') != entry['stage']:
            raise ImageBuildError('stage identity differs from package metadata')
    order(packages, plan['targets'])
    sync_tree(destination)
    return plan


def recorded_root(directory, binding, prepare):
    directory = Path(directory)
    marker = directory.with_suffix('.json')
    if not marker.exists():
        if directory.exists(): discard_staging(directory)
        prepare(directory)
        sync_tree(directory)
        write_json(marker, {'binding': binding, 'root': inventory(directory)})
    if json.loads(marker.read_text()) != {'binding': binding, 'root': inventory(directory)}:
        raise ImageBuildError('recorded bootstrap root changed')
    return directory


def restart_incomplete_stage(project, controller, stage_id):
    """Explicitly retire a failed stage; completed dependencies remain verified.

    Never infer permission to retry from a timeout. The caller must name the
    stage, and every submitted job must have a terminal outcome and cleanup.
    """
    from .box_control_adapter import BuildExecutionPending
    from zog.box_control.build_jobs import BuildJobs
    project = Path(project).resolve(); state = project / 'state'
    work = state / 'image-build/cross-bootstrap'
    names([stage_id])
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        operation = json.loads((work/'operation.json').read_text())
        builder = ImageBuild(package_dir=work/'recipes', state_dir=state,
                             runner=configured_runner(controller,state))
        with builder.locked():
            if operation['intent']['policy'] != builder._policy():
                raise ImageBuildError('restart execution policy changed')
            records = [p for p in (state/'image-build/pipelines').glob('*/pipeline.json')
                       if json.loads(p.read_text()).get('recipes') == operation['intent']['recipes']]
            if len(records) != 1: raise ImageBuildError('restart requires one unambiguous pipeline')
            record = json.loads(records[0].read_text())
            attempts = list(record['attempts'].values())
            if len(attempts)!=1: raise ImageBuildError('restart requires a single stage attempt')
            attempt = state/'image-build/attempts'/attempts[0]
            directory = attempt/'packages'/stage_id
            journal = work/('restart-'+stage_id+'.json')
            if journal.exists():
                restart = json.loads(journal.read_text())
                if restart['phase']=='complete': return restart
            else:
                if record['status']=='complete' or record.get('released'):
                    raise ImageBuildError('cannot restart a completed or released pipeline')
                if not directory.is_dir() or (directory/'result.json').exists():
                    raise ImageBuildError('only an incomplete stage can be restarted')
                control = builder.runner.execute.control
                failed = []
                for checkpoint in directory.glob('*.controller.json'):
                    saved = json.loads(checkpoint.read_text())
                    job = control.refresh_build_job(BuildJobs.job_id(saved['request_id']))
                    if job['outcome'] is None:
                        raise BuildExecutionPending(job)
                    if job['outcome'] != 'success':
                        failed.append(job['job_id'])
                        if job['outcome']=='unknown': job=control.cancel_build_job(job['job_id'])
                    if not job['process_cleanup_complete']: raise BuildExecutionPending(job)
                if not failed: raise ImageBuildError('no failed or unknown job authorizes restart')
                # Release only after terminal execution is proven. Keep all files and
                # original request/job identities in the retired stage directory.
                builder._release_resources(directory)
                restart = dict(schema=1,stage_id=stage_id,pipeline_id=record['pipeline_id'],
                               failed_jobs=failed,retired_name='retired-'+stage_id+'-'+uuid.uuid4().hex,
                               phase='retiring')
                write_json(journal,restart)
            retired = attempt/restart['retired_name']
            if not retired.exists(): directory.rename(retired)
            elif directory.exists(): raise ImageBuildError('ambiguous stage retirement')
            sync_tree(attempt)
            restart['phase']='complete';write_json(journal,restart)
            return restart


def run(project, catalogue, plan_path, controller, seed_path):
    project = Path(project).resolve(); state = project / 'state'
    work = state / 'image-build/cross-bootstrap'; ensure_directory(work)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan = stage_recipes(plan_path, catalogue, work / 'recipes')
        seed = read_selection(seed_path)
        if seed.manifest['kind'] != 'host-bootstrap':
            raise ImageBuildError('initial cross bootstrap requires a recorded distribution seed')
        builder = ImageBuild(package_dir=work/'recipes', state_dir=state, runner=configured_runner(controller, state))
        intent = {'plan': plan, 'recipes': inventory(work/'recipes'), 'seed': seed.generation, 'policy': builder._policy()}
        operation_path = work / 'operation.json'
        operation = json.loads(operation_path.read_text()) if operation_path.exists() else {'schema':1, 'intent':intent, 'phase':'stages'}
        if operation['intent'] != intent: raise ImageBuildError('bootstrap operation inputs changed')
        write_json(operation_path, operation)
        matches = []
        for path in (state/'image-build/pipelines').glob('*/pipeline.json'):
            saved = json.loads(path.read_text())
            if saved['operation']=='seed-check' and saved['selection']==str(seed.root.parent) and saved['arguments']['targets']==plan['targets'] and saved['recipes']==intent['recipes']:
                matches.append(path)
        if len(matches)>1: raise ImageBuildError('ambiguous bootstrap pipelines')
        result = builder.resume(matches[0].parent.name) if matches else builder.verify_seed(plan['targets'], host_bootstrap=seed)
        operation.update(phase='verify-link', stages_generation=result.generation);write_json(operation_path,operation)
        def build_root(root):
            shutil.copytree(seed.root,root,symlinks=True)
            merge(result.root,root,preserve_existing_directories=True)
        assembled = recorded_root(work/'cross-root', {'seed':seed.generation,'stages':result.generation}, build_root)
        target = plan['target']
        probe = r'''set -eu
cat > probe.c <<'EOF'
#include <stdio.h>
#include <string.h>
#include <gnu/libc-version.h>
#if __GLIBC__ != 2 || __GLIBC_MINOR__ != 44
#error wrong libc headers
#endif
int main(void) { const char *v=gnu_get_libc_version(); puts(v); return strcmp(v,"2.44") != 0; }
EOF
/tools/bin/TARGET-gcc probe.c -o /image-build/output/bootstrap-probe -v -Wl,--verbose > /image-build/output/link.txt 2>&1
/tools/bin/TARGET-readelf -l /image-build/output/bootstrap-probe > /image-build/output/interpreter.txt
/tools/bin/TARGET-readelf -d /image-build/output/bootstrap-probe > /image-build/output/dynamic.txt
grep -F '/lib64/ld-linux-x86-64.so.2' /image-build/output/interpreter.txt
grep -E '/sysroot/.*/(S?crt1|crti|crtn)\.o.*succeeded' /image-build/output/link.txt
grep -F '/sysroot/usr/include' /image-build/output/link.txt
grep -E '/sysroot/.*/libc.so.6.*succeeded' /image-build/output/link.txt
if grep -E '(RPATH|RUNPATH)' /image-build/output/dynamic.txt; then exit 1; fi
'''.replace('TARGET',target)
        attempts = state/'image-build/attempts'
        verify(builder,attempts/'cross-link-verification',assembled,[['/bin/bash','-c',probe]],result.generation)
        linked = attempts/'cross-link-verification/output'
        def runtime_root(root):
            shutil.copytree(result.root/'sysroot',root,symlinks=True)
            (root/'usr/bin').mkdir(exist_ok=True,parents=True)
            shutil.copy2(linked/'bootstrap-probe',root/'usr/bin/bootstrap-probe')
            for name in ('tmp','run','image-build/source','image-build/output'):(root/name).mkdir(parents=True,exist_ok=True)
        runtime = recorded_root(work/'runtime-root',{'stages':result.generation,'probe':inventory(linked)},runtime_root)
        operation.update(phase='verify-runtime');write_json(operation_path,operation)
        verify(builder,attempts/'cross-runtime-verification',runtime,[['/usr/bin/bootstrap-probe']],result.generation)
        with builder.locked():
            published = builder._publish(runtime,{'schema':2,'kind':'bootstrap-runtime','stages':result.generation,'outputs':inventory(runtime),'architecture':plan['architecture']},'bootstrap-runtime',{'self_hosted':False,'lfs_edition':plan['lfs_edition']})
        operation.update(phase='complete',runtime_generation=published.generation);write_json(operation_path,operation)
        return {'status':'complete','stages_generation':result.generation,'runtime_generation':published.generation,'operation':str(operation_path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','package-dir','plan','controller-config','seed'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--restart-incomplete-stage')
    args=parser.parse_args();logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    from .box_control_adapter import BuildExecutionPending
    try:
        if args.restart_incomplete_stage:
            restart_incomplete_stage(args.project,args.controller_config,args.restart_incomplete_stage)
        result=run(args.project,args.package_dir,args.plan,args.controller_config,args.seed)
    except BuildExecutionPending:
        print(json.dumps({'status':'pending','resume':'repeat the same command'}));raise SystemExit(75)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
