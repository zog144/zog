"""Non-accepting GCC diagnostics in a separately recorded offline fixture root."""
import argparse, fcntl, json, shutil
from pathlib import Path
from box_control import BoxControl, Project
from box_control.runtime.root_control import RootControlSystemdTransport
from zog.image_build.box_control_adapter import BoxControlExecutionAdapter, BuildExecutionPending
from zog.image_build.filesystem import inventory, write_json
from zog.image_build.local_network import install, FILES
from zog.image_build.metadata import identity
from zog.image_build.runner import BuildExecutionRequest
from zog.image_build.stages import recorded_root

def run(project, socket, failed_job, work):
    project, work = Path(project).resolve(), Path(work).resolve()
    if not work.is_relative_to(project/'state/image-build/attempts'):
        raise ValueError('diagnostic work must be beneath state/image-build/attempts')
    work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        c=BoxControl(Project(project),systemd_transport=RootControlSystemdTransport(Path(socket),timeout_seconds=600))
        old=c.inspect_build_job(failed_job)
        if not (old['state']=='completed' and old['exit_code']==1 and old['process_cleanup_complete'] and not old['resources_released']):
            raise ValueError('requires completed failed test with retained resources')
        request=old['request']
        resource=json.loads((project/'state/build-resource'/(request['build_root_id']+'.json')).read_text())['intent']
        original=Path(resource['prepared_root']);original_source=Path(resource['source_directory'])
        source=work/'source'
        recorded=json.loads((original.parent/'prepared.json').read_text())
        if inventory(original)!=recorded['root']:raise ValueError('original root changed')
        program=Path(__file__).with_name('gcc_diagnostic_commands.py').read_text()
        binding={'failed_job':failed_job,'invocation':old['invocation_id'],'original':recorded,'files':FILES,'program':program,'policy':request['resource_limits'],'original_source':str(original_source)}
        intent=work/'intent.json'
        if intent.exists() and json.loads(intent.read_text())!=binding:raise ValueError('diagnostic inputs changed')
        write_json(intent,binding)
        def prepare(root):
            shutil.copytree(original,root,symlinks=True);install(root)
        root=recorded_root(work/'root',identity(binding),prepare)
        # The controller forbids duplicate workspace registrations. Copy completed
        # compiler outputs into a private workspace; never share writable inodes.
        ready=work/'source-ready.json'
        if not ready.exists():
            if source.exists():raise ValueError('partial source copy requires inspection')
            shutil.copytree(original_source,source,symlinks=True)
            write_json(ready,{'source':str(original_source),'binding':identity(binding)})
        if json.loads(ready.read_text())!={'source':str(original_source),'binding':identity(binding)}:
            raise ValueError('diagnostic source binding changed')
        output=work/'output';output.mkdir(exist_ok=True)
        adapter=BoxControlExecutionAdapter(c,execution_user_id=request['execution_user_id'],execution_group_id=request['execution_group_id'],startup_timeout_seconds=30,termination_grace_seconds=5,wait_timeout_seconds=0,resource_limits=request['resource_limits'],input_manifest_id=identity(binding),device_profile=request['device_profile'])
        r=BuildExecutionRequest(root,source,output,('/usr/bin/python3','-c',program),request['environment'],'/image-build/source',3600)
        from zog.image_build.trace_records import capture_identity
        capture_identity(work/'diagnostics.log', attempt_id=work.name, command_id='diagnostics',
            package='gcc-final', stage_id='compiler-diagnostics', phase='test', command_index=0,
            category='diagnostic', provenance={'input_identity': identity(binding)},
            relationships=[{'relation':'diagnostic-of', 'target':{'job_id':failed_job}}])
        try:
            result=adapter.execute_for_attempt(r,work/'diagnostics.controller.json')
            return {'completed':True,'exit_code':result.exit_code,'acceptance':False}
        except BuildExecutionPending as pending:return {'job_id':pending.job_id,'state':pending.state,'acceptance':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('project','socket','failed-job','work'):p.add_argument('--'+key,required=True)
    print(json.dumps(run(**vars(p.parse_args()))),flush=True)
