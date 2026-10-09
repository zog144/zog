"""Accept an explicitly retained, tested GCC bootstrap without replaying compilation.

The caller supplies immutable job identities and the original controller-owned
workspace. No failed engine checkpoint is rewritten. Promotion requires fresh
installed-compiler and source-rebuild checks through the normal runner.
"""
import argparse
import fcntl
import json
import platform
import shutil
from pathlib import Path

from . import ImageBuild
from .configuration import configured_runner
from .developer.seed_build import verify
from .errors import ImageBuildError
from .filesystem import inventory, write_json
from .final_compiler import ACCEPTANCE, assemble, replacement_records, successful_execution
from .glibc_final import wait_for
from .metadata import identity
from .native import pipeline
from .stages import recorded_root, stage_recipes


def passed_job(controller, job_id):
    result = controller.refresh_build_job(job_id)
    if (result.get('state') != 'completed' or result.get('exit_code') != 0
            or result.get('process_cleanup_complete') is not True):
        raise ImageBuildError('retained compiler job has not passed and cleaned up: ' + job_id)
    return result


def passed_suite(result):
    if (result.get('status') != 'tests-passed' or result.get('command_exit') != 0
            or result.get('failures') != [] or result.get('missing') != []):
        raise ImageBuildError('retained compiler full suite has not passed')
    suites = result.get('suites', {})
    if not {'gcc.sum', 'g++.sum', 'libstdc++.sum'} <= {Path(x).name for x in suites}:
        raise ImageBuildError('retained compiler required suites missing')
    allowed = {'expected passes', 'expected failures', 'unsupported tests', 'untested testcases'}
    if any(c.get('expected passes', 0) < 1 or any(v and k not in allowed for k, v in c.items())
           for c in suites.values()):
        raise ImageBuildError('retained compiler unexpected suite result')
    return result


def installed_acceptance(version):
    if version != '15.3.0':
        raise ImageBuildError('retained acceptance supports the reviewed GCC 15.3.0 pin only')
    return ACCEPTANCE.replace('= 16.2.0', '= ' + version)


def run(project, catalogue, controller, retained, ownership, work, test_job, install_job):
    project, catalogue, retained, work = [Path(x).resolve() for x in (project, catalogue, retained, work)]
    work.mkdir(parents=True, exist_ok=True)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = project / 'state'
        runner = configured_runner(controller, state)
        # Use the same public controller API as the runner; never infer success from logs.
        from zog.box_control import BoxControl, Project
        from zog.box_control.runtime.root_control import RootControlSystemdTransport
        config = json.loads(Path(controller).read_text())
        control = BoxControl(Project(project), systemd_transport=RootControlSystemdTransport(
            Path(config['socket_path']), timeout_seconds=config['transport_timeout_seconds']))
        tests, install = [passed_job(control, j) for j in (test_job, install_job)]
        for key in ('build_root_id', 'source_workspace_id', 'output_workspace_id'):
            if tests['request'][key] != install['request'][key]:
                raise ImageBuildError('test and install workspace bindings differ')
        root_record = json.loads((retained / 'root.json').read_text())
        if root_record['root'] != inventory(retained / 'root'):
            raise ImageBuildError('retained compiler environment changed')
        registration = json.loads((retained / 'controller-resources.json').read_text())['registration']
        if Path(registration['prepared_root']).resolve() != retained / 'root':
            raise ImageBuildError('retained root registration differs')
        output = retained / 'output/pin-15.3.0-install'
        installed = json.loads((output / 'result.json').read_text())
        full = passed_suite(json.loads((retained / 'output/pin-15.3.0-full-acceptance/progress.json').read_text()))
        if installed.get('status') != 'installed-staging' or installed.get('tests') != full:
            raise ImageBuildError('installation does not bind to passing suite')
        bootstrap = json.loads((retained / 'output/pin-15.3.0/progress.json').read_text())
        steps = [x for x in bootstrap.get('steps', []) if x.get('phase') == 'bootstrap']
        if len(steps) != 1 or steps[0].get('exit_code') != 0 or not bootstrap.get('byte_swap_gate_passed'):
            raise ImageBuildError('retained GCC bootstrap comparison or byte-swap gate missing')
        if bootstrap.get('source_sha256') != 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb':
            raise ImageBuildError('retained GCC source differs from reviewed pin')
        version = installed['version']; acceptance = installed_acceptance(version)
        old = replacement_records(ownership)
        plan = stage_recipes(catalogue.parent / 'bootstrap/native-m4.py', catalogue, work / 'recipes-m4')
        builder = ImageBuild(package_dir=work / 'recipes-m4', state_dir=state,
                             runner=runner, maximum_generations=32)
        binding = {'test_job': test_job, 'install_job': install_job, 'test_invocation': tests['invocation_id'],
                   'install_invocation': install['invocation_id'], 'retained': str(retained),
                   'root': identity(root_record), 'full_suite': identity(full), 'bootstrap': identity(bootstrap),
                   'installed': inventory(output / 'root'), 'old_gcc': old['identity'],
                   'acceptance': acceptance, 'recipes': inventory(work / 'recipes-m4'),
                   'policy': builder._policy()}
        intent = work / 'intent.json'
        if intent.exists() and json.loads(intent.read_text()) != binding:
            raise ImageBuildError('retained compiler continuation inputs changed')
        write_json(intent, binding)
        result_path = work / 'result.json'
        if result_path.exists() and json.loads(result_path.read_text()).get('phase') == 'complete':
            return json.loads(result_path.read_text())
        try:
            write_json(work / 'progress.json', {'phase': 'composition'})
            root = recorded_root(work / 'compiler-root', identity(binding),
                lambda target: assemble(target, retained / 'root', [output / 'root'], [old]))
            attempt = state / 'image-build/attempts' / (work.name + '-installed')
            evidence = wait_for(work, 'installed-compiler', lambda: verify(builder, attempt, root,
                [['/bin/bash', '-eu', '-o', 'pipefail', '-c', acceptance]], identity(binding)))
            execution = successful_execution(attempt)
            with builder.locked():
                candidate = builder._publish(root, {'schema': 2, 'kind': 'native-compiler-candidate',
                    'architecture': platform.machine(), 'transition': identity(binding),
                    'outputs': inventory(root), 'verification': identity({'result': evidence, 'execution': execution})},
                    'native-compiler-candidate', {'source_built': True, 'self_hosted': False,
                    'build_environment_complete': True, 'verification_execution': execution})
            m4 = wait_for(work, 'm4-rebuild', lambda: pipeline(builder, candidate, plan['targets'], 'native-check'))
            probe = recorded_root(work / 'm4-probe-root', {'compiler': candidate.generation, 'm4': m4.generation},
                lambda target: (shutil.copytree(candidate.root, target, symlinks=True),
                               shutil.copytree(m4.root, target / 'selfhost-m4', symlinks=True)))
            m4_attempt = state / 'image-build/attempts' / (work.name + '-m4-installed')
            m4_evidence = wait_for(work, 'm4-installed', lambda: verify(builder, m4_attempt, probe,
                [['/bin/bash', '-eu', '-o', 'pipefail', '-c',
                  'printf "eval(6*7)\\n" | /selfhost-m4/usr/bin/m4 | grep -x 42']],
                {'compiler': candidate.generation, 'm4': m4.generation}))
            m4_execution = successful_execution(m4_attempt)
            with builder.locked():
                final = builder._publish(candidate.root, {'schema': 2, 'kind': 'toolchain', 'stage': 2,
                    'architecture': platform.machine(), 'parent': candidate.generation,
                    'bootstrap': 'gcc-three-stage-comparison', 'intent': identity(binding),
                    'acceptance': identity({'compiler': evidence, 'execution': execution,
                        'm4': m4_evidence, 'm4_execution': m4_execution}), 'outputs': inventory(candidate.root)},
                    'toolchain', {'stage': 2, 'self_hosted': True, 'source_built': True,
                                  'build_environment_complete': True})
                builder._activate(final, 'toolchain-active')
            result = {'phase': 'complete', 'generation': final.generation, 'root': str(final.root),
                      'self_hosted': True, 'gcc_version': version, 'm4_generation': m4.generation,
                      'test_job': test_job, 'install_job': install_job}
            write_json(result_path, result)
            return result
        except Exception as error:
            write_json(result_path, {'phase': 'failed', 'error': str(error), 'self_hosted': False})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'catalogue', 'controller', 'retained', 'ownership', 'work', 'test-job', 'install-job'):
        parser.add_argument('--' + name, required=True)
    print(json.dumps(run(**vars(parser.parse_args()))), flush=True)


if __name__ == '__main__':
    main()
