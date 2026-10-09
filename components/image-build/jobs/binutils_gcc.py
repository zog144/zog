"""Resume the final compiler sequence from an accepted test-tool environment.

Run as the orchestration user with the normal box-control runner configuration.
A superseded pipeline is explicitly released, retaining its failed evidence.
GCC starts only after Binutils finalization, composition and controller preflight.
This job does not promote a self-hosted toolchain.
"""
import argparse
import fcntl
import json
import logging
import platform
from pathlib import Path
from zog.image_build import ImageBuild, read_selection
from zog.image_build.artifacts import import_completed
from zog.image_build.configuration import configured_runner
from zog.image_build.developer.seed_build import verify
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory, write_json
from zog.image_build.final_compiler import PREFLIGHT, assemble, replacement_records, successful_execution
from zog.image_build.glibc_final import wait_for
from zog.image_build.metadata import identity
from zog.image_build.native import pipeline
from zog.image_build.stages import stage_recipes, recorded_root


def run(project, catalogue, controller, selection, ownership, work, superseded):
    project, catalogue, work = map(lambda p: Path(p).resolve(), (project, catalogue, work))
    state = project / 'state'
    work.mkdir(parents=True, exist_ok=True)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base = read_selection(selection)
        if not base.manifest.get('source_built') or not base.manifest.get('build_environment_complete'):
            raise ImageBuildError('requires accepted source-built compiler test environment')
        old = replacement_records(ownership)
        plans = {stage: stage_recipes(catalogue.parent / ('bootstrap/lfs-final-' + stage + '.py'),
                                     catalogue, work / ('recipes-' + stage))
                 for stage in ('binutils', 'gcc')}
        builder = ImageBuild(package_dir=work / 'recipes-binutils', state_dir=state,
                             runner=configured_runner(controller, state), maximum_generations=32)
        binding = {'base': base.generation, 'old_binutils': old, 'plans': plans,
                   'recipes': {stage: inventory(work / ('recipes-' + stage)) for stage in plans},
                   'policy': builder._policy(), 'preflight': PREFLIGHT, 'superseded': superseded}
        intent = work / 'intent.json'
        if intent.exists() and json.loads(intent.read_text()) != binding:
            raise ImageBuildError('recorded continuation inputs changed')
        write_json(intent, binding)
        try:
            if superseded:
                previous = builder.inspect_pipeline(superseded)
                if previous['selection'] != str(base.root.parent):
                    raise ImageBuildError('superseded pipeline has different build environment')
                if set(previous['arguments']['targets']) != set(plans['binutils']['targets']):
                    raise ImageBuildError('superseded pipeline has different targets')
                if previous['status'] not in ('pending', 'released'):
                    raise ImageBuildError('superseded pipeline must be stopped pending or released')
                if previous['status'] != 'released':
                    builder.release_pipeline(superseded)
                write_json(work / 'artifact-import.json', import_completed(builder, superseded))
            binutils = wait_for(work, 'binutils', lambda: pipeline(builder, base, plans['binutils']['targets'], 'native-check'))
            inputs = {'base': base.generation, 'binutils': binutils.generation,
                      'old_binutils': old['identity'], 'intent': identity(binding)}
            root = recorded_root(work / 'linker-root', inputs,
                                 lambda target: assemble(target, base.root, [binutils.root], [old]))
            attempt = state / 'image-build/attempts' / (work.name + '-linker-preflight')
            evidence = wait_for(work, 'linker-preflight', lambda: verify(builder, attempt, root,
                [['/bin/bash', '-eu', '-o', 'pipefail', '-c', PREFLIGHT]], inputs))
            execution = successful_execution(attempt)
            with builder.locked():
                linker = builder._publish(root, {'schema': 2, 'kind': 'native-compiler-candidate',
                    'architecture': platform.machine(), 'transition': inputs, 'outputs': inventory(root),
                    'verification': identity({'result': evidence, 'execution': execution})},
                    'native-compiler-candidate', {'source_built': True, 'self_hosted': False,
                    'build_environment_complete': True, 'verification_execution': execution})
            write_json(work / 'binutils-accepted.json', {'outputs': binutils.generation, 'environment': linker.generation})
            logging.info('Binutils accepted; starting GCC with environment %s', linker.generation)
            builder.package_dir = work / 'recipes-gcc'
            gcc = wait_for(work, 'gcc', lambda: pipeline(builder, linker, plans['gcc']['targets'], 'native-check'))
            result = {'phase': 'complete', 'binutils': binutils.generation, 'linker_environment': linker.generation,
                      'gcc_outputs': gcc.generation, 'self_hosted': False,
                      'remaining': 'Compose GCC, run installed compiler acceptance and rebuild M4'}
            write_json(work / 'result.json', result)
            return result
        except Exception as error:
            write_json(work / 'result.json', {'phase': 'failed', 'error': str(error), 'self_hosted': False})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'catalogue', 'controller', 'selection', 'ownership', 'work'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--superseded', default=None)
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(**vars(parser.parse_args()))), flush=True)
