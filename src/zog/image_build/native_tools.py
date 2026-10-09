"""Durable native-tool prerequisites and compiler stages with installed evidence."""
import argparse
import fcntl
import json
import platform
from dataclasses import replace
from pathlib import Path

from . import ImageBuild, read_selection
from .configuration import configured_runner
from .developer.seed_build import verify
from .filesystem import inventory, write_json
from .final_compiler import successful_execution
from .generation_provenance import prepare, finish, verify as verify_generation
from .glibc_final import wait_for
from .metadata import Package, load_packages, order
from .provenance import Provenance
from .stages import stage_recipes
from . import host_labels, installed_verification


def retained_output(state, name, record):
    """Locate intact copies of the exact finalized output and canonical binding."""
    expected = {k:v for k,v in record.items() if k != 'provenance'}
    for path in sorted((Path(state)/'image-build/attempts').glob('*/packages/'+name+'/result.json')):
        candidate = json.loads(path.read_text())
        if {k:v for k,v in candidate.items() if k != 'provenance'} != expected:
            continue
        binding = candidate.get('provenance')
        if binding is None and (path.parent/'provenance.json').exists():
            saved = json.loads((path.parent/'provenance.json').read_text())
            binding = {k:saved.get(k) for k in ('output','result')}
        if binding != record.get('provenance'):
            continue
        root = path.parent/'output'
        if root.is_dir() and inventory(root) == record['outputs']:
            return root
    raise ValueError('No intact retained package output with exact provenance: '+name)


def run(project, catalogue, controller, selection, work, source_revision, host_id, project_id, base_components, plan_file, check_file, retry_of=None, pin_revision=None):
    project, catalogue, controller, selection, work = map(lambda x: Path(x).resolve(),
        (project, catalogue, controller, selection, work))
    work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = project/'state'
        base = read_selection(selection)
        if not base.manifest.get('python_runtime_verified') or not base.manifest.get('public_trust_store_verified'):
            raise ValueError('Accepted Python and public CA generation required')
        plan = stage_recipes(Path(plan_file).resolve(), catalogue, work/'recipes')
        definitions = load_packages(work/'recipes')
        pin = Provenance.capture_pin(state, catalogue.parent/'pins/2026-10-01/commit-pin.py',
            repository='https://github.com/zog144/image-build', revision=pin_revision or source_revision,
            repository_path='project/pins/2026-10-01/commit-pin.py')
        provenance = Provenance(state, host_id=host_id, project_id=project_id, pin=pin,
            retry_of=json.loads(Path(retry_of).read_text()) if retry_of else None)
        builder = ImageBuild(package_dir=work/'recipes', state_dir=state,
            runner=configured_runner(controller, state), maximum_generations=32, provenance=provenance)
        components = json.loads(Path(base_components).read_text())
        if set(components) != set(base.manifest['packages']):
            raise ValueError('Exact accepted base package set required')
        built = {}
        for name, path in components.items():
            record = dict(base.manifest['packages'][name], root=str(Path(path).resolve()))
            if inventory(record['root']) != record['outputs']:
                raise ValueError('Accepted base component changed: '+name)
            provenance.verify_output(record['provenance'], name, record)
            built[name] = record
        check = Path(check_file).read_text()
        if not check.strip():
            raise ValueError('Installed verification command required')
        intent = dict(source_revision=source_revision, base=base.generation, base_components=components, recipes=inventory(work/'recipes'),
                      policy=builder._policy(), check=check, plan=plan,
                      verification_report_contract=installed_verification.CONTRACT, provenance=provenance.configuration())
        saved = work/'intent.json'
        if saved.exists() and json.loads(saved.read_text()) != intent:
            raise ValueError('Frozen native tool attempt changed')
        write_json(saved, intent)
        def build():
            matches = []
            for f in (state/'image-build/pipelines').glob('*/pipeline.json'):
                r = json.loads(f.read_text())
                if (not r.get('released') and r['operation']=='image' and r['selection']==str(selection)
                        and r['recipes']==intent['recipes'] and r['arguments']['targets']==plan['targets']
                        and r['policy']==intent['policy']):
                    matches.append(r['pipeline_id'])
            if len(matches)>1:
                raise ValueError('Ambiguous native tool pipeline')
            return builder.resume(matches[0]) if matches else builder.ensure(plan['targets'], toolchain=base)
        packages = wait_for(work, 'native-packages', build)
        # Recover the exact finalized per-package outputs, never substitute the
        # composed package generation for an individual package's inventory.
        for name, record in packages.manifest['packages'].items():
            built[name] = dict(record, root=str(retained_output(state, name, record)))
        for name in components:
            definitions[name] = Package(name, (), (), (), {}, {}, (), {})
        # Every selected addition explicitly carries the inherited base into the
        # runtime composition. Preserve original output/result bindings verbatim.
        for name in plan['targets']:
            definitions[name] = replace(definitions[name], runtime_dependencies=tuple(dict.fromkeys(
                (*components, *definitions[name].runtime_dependencies))))
        targets = plan['targets']
        attempt = state/'image-build/attempts'/(work.name+'-assembly')
        with builder.locked():
            labels = host_labels.snapshot(built)
            material = provenance._bytes('host-label-omissions.json', labels)
            inputs = dict(schema=2, kind='toolchain', stage=2, architecture=platform.machine(),
                assembly_attempt=attempt.name, source_revision=source_revision, base=base.generation, packages=packages.generation,
                base_generation_record=base.manifest['build_record'], verification_command=check,
                execution_policy=builder._policy(), provenance=provenance.configuration(),
                verification_report_contract=installed_verification.CONTRACT,
                verification_check="installed-native-tools",
                composition_policy=host_labels.POLICY, host_label_evidence=material)
            assembly = prepare(provenance, attempt, definitions, targets, built, inputs,
                               composition_materials=[material])
            root = host_labels.compose(attempt, built, order(definitions, targets, runtime_only=True), labels)
        verification = state/'image-build/attempts'/(work.name+'-installed')
        wait_for(work, 'installed-native-tools', lambda: verify(builder, verification, root,
            [['/bin/bash','-eu','-c',check]], inputs))
        execution = successful_execution(verification)
        with builder.locked():
            report = installed_verification.capture(provenance, assembly, root, inputs, verification, execution)
            pointer = finish(provenance, attempt, assembly, root, verification=[report])
            accepted = builder._publish(root, inputs, 'toolchain', dict(stage=2, self_hosted=True,
                source_built=True, build_environment_complete=True, python_runtime_verified=True,
                public_trust_store_verified=True, python_packaging_verified=True,
                python_enrollment_complete=False, public_https_handshake_verified=False,
                native_tool_targets=plan['targets'],
                packages={n:{k:v for k,v in r.items() if k!='root'} for n,r in built.items()},
                build_record=pointer, verification_execution=execution,
                test_exceptions=base.manifest.get('test_exceptions',[])))
        from zog.build_record.model import canonical
        bundle = verify_generation(provenance, accepted)
        (work/'canonical-generation.json').write_bytes(canonical(bundle))
        snapshot = builder.selected_observation_snapshot(accepted.generation)
        result = dict(phase='complete', generation=accepted.generation, root=str(accepted.root),
            package_generation=packages.generation, canonical_record=pointer['record'],
            observation_snapshot=snapshot['snapshot'],
            canonical_export=str(work/'canonical-generation.json'), record_store=str(provenance.store.directory),
            verification_execution=execution, remaining=['maturin','cryptography',
                'http-message-signatures','host-identify','host-discover','host-install','outbound HTTPS acceptance'])
        write_json(work/'result.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project','catalogue','controller','selection','work','source-revision','host-id','project-id','base-components','plan-file','check-file'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--retry-of')
    parser.add_argument('--pin-revision', help='Commit containing the unchanged monthly pin; defaults to source revision')
    print(json.dumps(run(**vars(parser.parse_args()))), flush=True)

if __name__=='__main__':
    main()
