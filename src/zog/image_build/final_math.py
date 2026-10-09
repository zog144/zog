"""Detached, resumable prerequisite graph using the accepted final libc root."""
import argparse
import fcntl
import json
import logging
from pathlib import Path
from .configuration import configured_runner
from .engine import ImageBuild, read_selection
from .filesystem import inventory, write_json
from .glibc_final import wait_for
from .native import pipeline
from .stages import stage_recipes
from .errors import ImageBuildError
from .info_index import POLICY as INFO_INDEX_POLICY


def run(project, catalogue, controller, selection, work):
    project, catalogue, work = (Path(p).resolve() for p in (project, catalogue, work))
    state = project / 'state'
    work.mkdir(parents=True, exist_ok=True)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base = read_selection(selection)
        if base.manifest['kind'] != 'native-final-libc':
            raise ImageBuildError('arithmetic prerequisites require verified final libc')
        plan = stage_recipes(catalogue.parent / 'bootstrap/lfs-final-math.py', catalogue, work / 'recipes')
        builder = ImageBuild(package_dir=work / 'recipes', state_dir=state,
                             runner=configured_runner(controller, state), maximum_generations=24)
        intent = {'base': base.generation, 'plan': plan, 'recipes': inventory(work / 'recipes'),
                  'policy': builder._policy(), 'maximum_generations': 24, 'composition_policy': INFO_INDEX_POLICY}
        path = work / 'intent.json'
        if path.exists() and json.loads(path.read_text()) != intent:
            raise ImageBuildError('recorded arithmetic graph inputs changed')
        write_json(path, intent)
        result_path = work / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if result['phase'] != 'complete':
                raise ImageBuildError('inspect retained failure before another operation')
            read_selection(state / 'image-build/generations' / result['generation'])
            return result
        try:
            result = wait_for(work, 'arithmetic-stages',
                              lambda: pipeline(builder, base, plan['targets'], 'native-check'))
            record = {'phase': 'complete', 'generation': result.generation,
                      'base_generation': base.generation, 'self_hosted': False,
                      'scope': 'GMP, MPFR and MPC package outputs; not a promoted compiler root'}
            write_json(result_path, record)
            print(json.dumps(record), flush=True)
            return record
        except Exception as error:
            write_json(result_path, {'phase': 'failed', 'error': str(error)})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'catalogue', 'controller', 'selection', 'work'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run(**vars(args))


if __name__ == '__main__':
    main()
