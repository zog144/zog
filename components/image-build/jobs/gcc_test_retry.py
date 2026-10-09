"""Explicit test-only retry; retains failed pipeline and reuses completed compilation."""
import argparse
import fcntl
import json
from pathlib import Path

from box_control import BoxControl, Project
from box_control.runtime.root_control import RootControlSystemdTransport
from zog.image_build.filesystem import write_json
from zog.image_build.metadata import identity

STACK_BYTES = 256 * 1024 * 1024
PREFIX = 'ulimit -s unlimited\n'
REPLACEMENT = ('ulimit -s 262144\n'
               'python3 -c "import resource; assert resource.getrlimit(resource.RLIMIT_STACK) == '
               '(268435456, 268435456); print(\'Verified stack limit: 256 MiB\')"\n')


def retry_request(failed, built):
    if (failed['state'] != 'completed' or failed['exit_code'] != 1
            or not failed['process_cleanup_complete'] or failed['resources_released']):
        raise ValueError('failed test must be stopped with retained resources')
    if (built['state'] != 'completed' or built['exit_code'] != 0
            or not built['process_cleanup_complete']):
        raise ValueError('successful completed compilation required')
    for key in ('build_root_id','source_workspace_id','output_workspace_id'):
        if failed['request'][key] != built['request'][key]:
            raise ValueError('test and compilation resources differ')
    request = json.loads(json.dumps(failed['request']))
    argv = request['command']
    if argv[:5] != ['/bin/bash','-eu','-o','pipefail','-c'] or len(argv) != 6 or not argv[5].startswith(PREFIX):
        raise ValueError('unexpected failed GCC test command')
    request['command'][5] = REPLACEMENT + argv[5][len(PREFIX):]
    request['resource_limits']['stack-maximum-bytes'] = STACK_BYTES
    return request


def run(project, socket, failed_job, build_job, work):
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        c = BoxControl(Project(Path(project)), systemd_transport=RootControlSystemdTransport(Path(socket), timeout_seconds=600))
        failed = c.inspect_build_job(failed_job); built = c.inspect_build_job(build_job)
        request = retry_request(failed, built)
        binding = {'failed_job':failed_job, 'build_job':build_job, 'request':request,
                   'failed_invocation':failed['invocation_id'], 'build_invocation':built['invocation_id']}
        path = work/'request.json'
        if path.exists():
            saved = json.loads(path.read_text())
            if saved['binding'] != binding: raise ValueError('retry inputs changed')
        else:
            saved = {'binding':binding, 'request_id':c.issue_build_request_id()}
            write_json(path, saved)
        result = c.submit_build_job(request_id=saved['request_id'], **request)
        write_json(work/'job.json', result)
        return {k:result.get(k) for k in ('job_id','state','invocation_id','exit_code')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('project','socket','failed-job','build-job','work'): p.add_argument('--'+key, required=True)
    print(json.dumps(run(**vars(p.parse_args()))))
