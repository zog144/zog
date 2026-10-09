"""Verify and publish an already composed Glibc candidate under a new operation."""
import argparse
import fcntl
import json
import logging
import os
import platform
from pathlib import Path
from .configuration import configured_runner
from .developer.seed_build import verify
from .engine import ImageBuild
from .filesystem import inventory,digest,write_json
from .glibc_final import PROBE,accepted_summary,wait_for
from .metadata import identity


def run(project,previous,work,controller):
    project=Path(project).resolve();previous=Path(previous).resolve();work=Path(work).resolve()
    assert os.getuid()!=0
    work.mkdir(parents=True,exist_ok=True)
    with (work/'operation.lock').open('a+') as lock,(previous/'operation.lock').open('a+') as prior_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(prior_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (work/'result.json').exists():raise RuntimeError('Inspect the recorded publication result')
        state=project/'state';runner=configured_runner(controller,state)
        old=json.loads((previous/'intent.json').read_text());evidence=old['evidence']
        assert evidence['counts']==accepted_summary((previous.parent/'attempts/glibc-clean-suite-pass1/output/result-recovery-tests.sum').read_text())
        source_summary=previous.parent/'attempts/glibc-clean-suite-pass1/output/result-recovery-tests.sum'
        assert digest(source_summary)==evidence['summary_sha256']
        root=previous/'verified-root';record=json.loads((previous/'verified-root.json').read_text())
        assert record['root']==inventory(root), 'Prepared candidate changed'
        package=json.loads((previous/'package-manifest.json').read_text())['outputs']
        expected={r['path']:r for r in package}
        assert digest(root/'usr/lib/libc.so.6')==expected['usr/lib/libc.so.6']['sha256']
        assert digest(root/'usr/lib/ld-linux-x86-64.so.2')==expected['usr/lib/ld-linux-x86-64.so.2']['sha256']
        prior_job_dir=state/'image-build/attempts'/(previous.name+'-verify')
        prior_checkpoint=json.loads((prior_job_dir/'command-0.controller.json').read_text())
        prior_job=runner.execute.control.refresh_build_job(prior_checkpoint['job_id'])
        assert prior_job['process_cleanup_complete'] and prior_job['outcome']=='nonzero-exit'
        # Retain the old failure and output evidence; only release controller resources.
        runner.execute.release_resources(prior_job_dir)
        probe=PROBE.replace('LIBC_HASH',expected['usr/lib/libc.so.6']['sha256']).replace('LOADER_HASH',expected['usr/lib/ld-linux-x86-64.so.2']['sha256'])
        binding={'previous_intent':identity(old),'root':record,'probe':probe,'policy':runner.execute.configuration(),
                 'previous_failed_job':prior_job['job_id']}
        if (work/'intent.json').exists():assert json.loads((work/'intent.json').read_text())==binding
        else:write_json(work/'intent.json',binding)
        builder=ImageBuild(package_dir=work,state_dir=state,runner=runner,maximum_generations=16)
        verification=state/'image-build/attempts'/(work.name+'-verify')
        try:
            write_json(work/'progress.json',{'phase':'prepare-verification'})
            result=wait_for(work,'verify',lambda:verify(builder,verification,root,[['/bin/bash','-eu','-c',probe]],identity(binding)))
            completion=json.loads((verification/'command-0.execution.json').read_text())
            assert completion['exit_code']==0 and completion['cleanup_complete']
            write_json(work/'progress.json',{'phase':'publish'})
            with builder.locked():
                selection=builder._publish(root,{'schema':2,'kind':'native-final-libc','architecture':platform.machine(),'base':evidence['base_generation'],
                    'package':package,'acceptance':identity(evidence),'outputs':record['root'],
                    'verification':identity({'binding':binding,'completion':completion})},
                    'native-final-libc',{'source_built':True,'self_hosted':False,'build_environment_complete':True,
                    'glibc_version':'2.44','test_counts':evidence['counts'],'verification':result,
                    'verification_execution':completion})
            write_json(work/'result.json',{'phase':'complete','generation':selection.generation,'root':str(selection.root),
                 'self_hosted':False,'installed':True,'published':True})
            print('PUBLISHED FINAL GLIBC',selection.generation,flush=True)
        except Exception as error:
            write_json(work/'result.json',{'phase':'failed','error':str(error),'published':False});raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','previous','work','controller'):parser.add_argument('--'+name,required=True)
    a=parser.parse_args();logging.basicConfig(level=logging.INFO);run(a.project,a.previous,a.work,a.controller)
if __name__=='__main__':main()
