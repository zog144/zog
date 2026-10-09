"""Build pinned Mozilla TLS trust and verify the installed default trust store."""
import argparse
import fcntl
import json
import platform
import shutil
from dataclasses import replace
from pathlib import Path
from . import ImageBuild, read_selection
from .configuration import configured_runner
from .developer.seed_build import verify
from .filesystem import inventory, merge, write_json
from .glibc_final import wait_for
from .stages import recorded_root, stage_recipes
from .final_compiler import successful_execution
from . import installed_verification

CHECK = "set -eu\npython3 -I - <<'ZOG_TRUST'\nimport json,ssl,hashlib,pathlib\npaths=ssl.get_default_verify_paths()\nassert paths.cafile == '/etc/ssl/cert.pem', paths\ncontext=ssl.create_default_context()\ncerts=context.get_ca_certs(binary_form=True)\nassert len(certs)>=100, len(certs)\nassert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname\nprint(json.dumps({'default_cafile':paths.cafile,'ca_count':len(certs),'bundle_sha256':hashlib.sha256(pathlib.Path(paths.cafile).read_bytes()).hexdigest()}))\nZOG_TRUST\n"

def run(project, catalogue, controller, selection, work, chain, source_revision, host_id, project_id, maximum_generations=32):
    project,catalogue,controller,selection,work=map(lambda p:Path(p).resolve(),(project,catalogue,controller,selection,work))
    work.mkdir(parents=True,exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        base=read_selection(selection)
        if base.manifest.get('kind')!='toolchain' or not base.manifest.get('self_hosted') or base.manifest.get('stage')!=2:
            raise ValueError('Libraries require an accepted self-hosted toolchain')
        if not base.manifest.get('python_runtime_verified'):raise ValueError('Verified Python runtime required')
        chain=Path(chain).read_text()
        if not chain or len(chain)>65536 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/= -\n\r' for c in chain):raise ValueError('Invalid PEM chain fixture')
        certificates=chain.split('-----END CERTIFICATE-----')
        certificates=[c.strip()+'\n-----END CERTIFICATE-----\n' for c in certificates if c.strip()]
        if len(certificates)<2:raise ValueError('Public chain fixture requires leaf and intermediate')
        check=CHECK+'cat > leaf.pem <<\'ZOG_LEAF\'\n'+certificates[0]+'ZOG_LEAF\ncat > intermediates.pem <<\'ZOG_INTERMEDIATE\'\n'+''.join(certificates[1:])+'ZOG_INTERMEDIATE\nopenssl verify -purpose sslserver -verify_hostname www.python.org -untrusted intermediates.pem leaf.pem\nif openssl verify -purpose sslserver -verify_hostname wrong.invalid -untrusted intermediates.pem leaf.pem; then exit 1; fi\n'
        plan=stage_recipes(catalogue.parent/'bootstrap/host-trust.py',catalogue,work/'recipes')
        from .provenance import Provenance
        pin=Provenance.capture_pin(project/'state',catalogue.parent/'pins/2026-10-01/commit-pin.py',repository='https://github.com/zog144/image-build',revision=source_revision,repository_path='project/pins/2026-10-01/commit-pin.py')
        provenance=Provenance(project/'state',host_id=host_id,project_id=project_id,pin=pin)
        builder=ImageBuild(package_dir=work/'recipes',state_dir=project/'state',runner=configured_runner(controller,project/'state'),maximum_generations=maximum_generations,provenance=provenance)
        intent={'base':base.generation,'recipes':inventory(work/'recipes'),'policy':builder._policy(),'verification_command':check,'provenance':provenance.configuration(),'verification_report_contract':installed_verification.CONTRACT}
        saved=work/'intent.json'
        if saved.exists() and json.loads(saved.read_text())!=intent:raise ValueError('Library build inputs changed')
        write_json(saved,intent)
        def build():
            matches=[]
            for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json'):
                r=json.loads(p.read_text())
                if not r.get('released') and r['operation']=='image' and r['selection']==str(base.root.parent) and r['recipes']==intent['recipes'] and r['arguments']['targets']==plan['targets']:matches.append(r['pipeline_id'])
            if len(matches)>1:raise ValueError('Ambiguous library pipeline')
            return builder.resume(matches[0]) if matches else builder.ensure(plan['targets'],toolchain=base)
        packages=wait_for(work,'trust-data',build)
        from .metadata import Package,load_packages,identity
        from .generation_provenance import prepare,finish,verify as verify_generation
        base_record={'inputs':base.manifest['inputs'],'outputs':base.manifest['outputs']}
        base_record['identity']=identity(base_record)
        base_record['provenance']=provenance.legacy_output('accepted-python-base',base_record)
        base_record['root']=str(base.root)
        definitions=load_packages(work/'recipes')
        definitions['accepted-python-base']=Package('accepted-python-base',(),(),(),{}, {},(),{})
        definitions['ca-certificates-final']=replace(definitions['ca-certificates-final'],runtime_dependencies=('accepted-python-base',))
        ca_record=dict(packages.manifest['packages']['ca-certificates-final'],root=str(packages.root))
        built={'accepted-python-base':base_record,'ca-certificates-final':ca_record}
        attempt=builder.state/'image-build/attempts'/(work.name+'-assembly')
        owner_inputs={'schema':2,'kind':'toolchain','stage':2,'architecture':platform.machine(),'base':base.generation,'trust_data':packages.generation,'verification_command':check,'provenance':provenance.configuration(),'execution_policy':builder._policy(),'verification_report_contract':installed_verification.CONTRACT}
        with builder.locked():
            assembly=prepare(provenance,attempt,definitions,['ca-certificates-final'],built,owner_inputs)
            records=builder._compose(definitions,['ca-certificates-final'],built,attempt/'composed')
        root=attempt/'composed'
        verification_attempt=builder.state/'image-build/attempts'/work.name
        evidence=wait_for(work,'installed-trust',lambda:verify(builder,verification_attempt,root,[['/bin/bash','-eu','-c',check]],owner_inputs))
        execution=successful_execution(verification_attempt)
        with builder.locked():
            report=installed_verification.capture(provenance,assembly,root,owner_inputs,verification_attempt,execution)
            pointer=finish(provenance,attempt,assembly,root,verification=[report])
            accepted=builder._publish(root,owner_inputs,'toolchain',{'stage':2,'self_hosted':True,'source_built':True,'build_environment_complete':True,'packages':records,'build_record':pointer,'verification_execution':execution,'python_runtime_verified':True,'public_trust_store_verified':True,'public_https_handshake_verified':False,'test_exceptions':base.manifest.get('test_exceptions',[])})
        from zog.build_record.model import canonical
        bundle=verify_generation(provenance,accepted)
        (work/'canonical-generation.json').write_bytes(canonical(bundle))
        snapshot=builder.selected_observation_snapshot(accepted.generation)
        result={'phase':'complete','base':base.generation,'packages':packages.generation,'generation':accepted.generation,'root':str(accepted.root),'public_trust_store_verified':True,'public_https_handshake_verified':False,'canonical_record':pointer['record'],'observation_snapshot':snapshot['snapshot'],'record_store':str(provenance.store.directory),'canonical_export':str(work/'canonical-generation.json')}
        write_json(work/'result.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','catalogue','controller','selection','work','chain','source-revision','host-id','project-id'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--maximum-generations',type=int,default=32)
    print(json.dumps(run(**vars(parser.parse_args()))),flush=True)

if __name__=='__main__':main()
