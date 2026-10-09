"""New CA assembly from accepted outputs; never re-execute an old package attempt."""
import argparse
import fcntl
import json
import platform
from pathlib import Path
from . import ImageBuild, read_selection
from .configuration import configured_runner
from .developer.seed_build import verify
from .filesystem import write_json
from .glibc_final import wait_for
from .final_compiler import successful_execution
from .metadata import Package, identity
from .provenance import Provenance
from .generation_provenance import prepare, finish, verify as verify_generation
from . import host_labels, installed_verification


def run(project, previous_work, package_attempt, work):
    project, previous_work, package_attempt, work = map(lambda p: Path(p).resolve(),
        (project, previous_work, package_attempt, work))
    state = project/'state'
    if work == previous_work or package_attempt.parent != state/'image-build/attempts':
        raise ValueError('New assembly work and an existing project attempt required')
    work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prior = json.loads((previous_work/'intent.json').read_text())
        p = Provenance.from_configuration(state, prior['provenance'])
        base = read_selection(state/'image-build/generations'/prior['base'])
        if not base.manifest.get('python_runtime_verified'):
            raise ValueError('Accepted Python base required')
        package = package_attempt/'packages/ca-certificates-final'
        binding = json.loads((package/'provenance.json').read_text())
        if (binding['build_id'] != 'attempt:'+package_attempt.name or
                binding['package'] != 'ca-certificates-final' or not binding['result']):
            raise ValueError('Accepted CA package binding required')
        ca = json.loads((package/'result.json').read_text())
        ca.update(root=str(package/'output'), provenance={k: binding[k] for k in ('output','result')})
        p.verify_output(ca['provenance'], 'ca-certificates-final', ca)
        legacy = {'inputs':base.manifest['inputs'], 'outputs':base.manifest['outputs']}
        legacy['identity'] = identity(legacy)
        legacy.update(root=str(base.root), provenance=p.legacy_output('accepted-python-base',legacy))
        built = {'accepted-python-base':legacy, 'ca-certificates-final':ca}
        definitions = {
            'accepted-python-base':Package('accepted-python-base',(),(),(),{}, {},(),{})}
        # Package fields are named explicitly to avoid coupling runtime order to
        # dataclass positional layout.
        from dataclasses import replace
        definitions['ca-certificates-final'] = replace(definitions['accepted-python-base'],
            name='ca-certificates-final',runtime_dependencies=('accepted-python-base',))
        builder = ImageBuild(package_dir=previous_work/'recipes',state_dir=state,
            runner=configured_runner(previous_work/'controller.json',state),
            maximum_generations=32,provenance=p)
        if builder._policy() != prior['policy']:
            raise ValueError('Original installed-check execution policy differs')
        attempt = state/'image-build/attempts'/(work.name+'-assembly')
        check = prior['verification_command']
        with builder.locked():
            labels = host_labels.snapshot(built)
            material = p._bytes('host-label-omissions.json', labels)
            owner_inputs = {'schema':2,'kind':'toolchain','stage':2,
                'architecture':platform.machine(),'base':base.generation,
                'assembly_attempt':attempt.name,
                'ca_output':ca['provenance'], 'previous_attempt':package_attempt.name,
                'composition_policy':host_labels.POLICY,'host_label_evidence':material,
                'verification_command':check,'execution_policy':prior['policy'],
                'verification_report_contract':installed_verification.CONTRACT,
                'provenance':p.configuration()}
            saved = work/'intent.json'
            if saved.exists() and json.loads(saved.read_text()) != owner_inputs:
                raise ValueError('Assembly inputs changed')
            write_json(saved,owner_inputs)
            assembly = prepare(p,attempt,definitions,['ca-certificates-final'],built,
                               owner_inputs,composition_materials=[material])
            root = host_labels.compose(attempt,built,['accepted-python-base','ca-certificates-final'],labels)
        verification_attempt = state/'image-build/attempts'/work.name
        wait_for(work,'installed-trust',lambda:verify(builder,verification_attempt,root,
            [['/bin/bash','-eu','-c',check]],owner_inputs))
        execution = successful_execution(verification_attempt)
        with builder.locked():
            report = installed_verification.capture(p,assembly,root,owner_inputs,verification_attempt,execution)
            pointer = finish(p,attempt,assembly,root,verification=[report])
            records = {name:{k:v for k,v in record.items() if k!='root'} for name,record in built.items()}
            accepted = builder._publish(root,owner_inputs,'toolchain',{
                'stage':2,'self_hosted':True,'source_built':True,'build_environment_complete':True,
                'packages':records,'build_record':pointer,'verification_execution':execution,
                'python_runtime_verified':True,'public_trust_store_verified':True,
                'public_https_handshake_verified':False,'test_exceptions':base.manifest.get('test_exceptions',[])})
        from zog.build_record.model import canonical
        bundle = verify_generation(p,accepted)
        (work/'canonical-generation.json').write_bytes(canonical(bundle))
        snapshot = builder.selected_observation_snapshot(accepted.generation)
        result = {'phase':'complete','generation':accepted.generation,'root':str(accepted.root),
            'canonical_record':pointer['record'],'observation_snapshot':snapshot['snapshot'],
            'record_store':str(p.store.directory),
            'canonical_export':str(work/'canonical-generation.json'),'verification_execution':execution,
            'package_attempt':package_attempt.name,'assembly_attempt':attempt.name}
        write_json(work/'result.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','previous-work','package-attempt','work'):
        parser.add_argument('--'+name,required=True)
    print(json.dumps(run(**vars(parser.parse_args()))),flush=True)

if __name__=='__main__': main()
