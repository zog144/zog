"""Repeatable distribution seed verification and first source-build milestone."""
import argparse
import fcntl
import json
import logging
from pathlib import Path
import shutil

from .seed import prepare
from .. import ImageBuild, read_selection
from ..configuration import configured_runner
from ..errors import ImageBuildError
from ..filesystem import inventory, sync_tree, write_json, ensure_directory, discard_staging
from ..metadata import identity
from ..cleanup import discard_work

PROBE = r'''set -eu
[ "$(id -u)" != 0 ]
[ "$(readlink -f /bin/sh)" = /usr/bin/bash ]
[ "$(readlink -f /usr/bin/awk)" = /usr/bin/gawk ]
yacc --version | grep -i bison
for tool in bash ld bison sort diff find gawk gcc g++ grep gzip m4 make patch perl python3 sed tar texi2any xz; do command -v "$tool"; done
[ ! -e /root/zog-seed-host-sentinel ]
[ ! -S /run/dbus/system_bus_socket ]
if touch /usr/zog-forbidden 2>/dev/null; then exit 1; fi
python3 -c 'import os; a,b=os.openpty(); os.close(a); os.close(b)'
printf '#include <stdio.h>\nint main(){puts("C seed OK");}\n' > c.c
printf '#include <iostream>\nint main(){std::cout << "C++ seed OK";}\n' > cxx.cc
gcc c.c -o /image-build/output/c
g++ cxx.cc -o /image-build/output/cxx
/image-build/output/c
/image-build/output/cxx
readelf -l /image-build/output/cxx
ldd /image-build/output/cxx
gcc -print-search-dirs
g++ -print-file-name=libstdc++.so
python3 -c 'import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(("1.1.1.1",53)); assert r != 0, "network unexpectedly reachable"'
'''


def verify(builder, folder, root, commands, binding):
    """Controller completion checkpoints are reused, never inferred from log text."""
    folder = Path(folder)
    ensure_directory(folder)
    prepared = folder / 'prepared.json'
    complete = folder / 'verification.json'
    if not prepared.exists():
        if (folder / 'controller-resources.json').exists():
            raise ImageBuildError('unrecorded verification with controller resources')
        for name in ('root', 'source', 'output'):
            if (folder / name).exists():
                discard_staging(folder / name)
        shutil.copytree(root, folder / 'root', symlinks=True)
        (folder / 'source').mkdir(); (folder / 'output').mkdir()
        sync_tree(folder)
        write_json(prepared, {'root': inventory(folder / 'root'), 'binding': binding, 'commands': commands})
    saved = json.loads(prepared.read_text())
    if complete.exists():
        result = json.loads(complete.read_text())
        if saved['binding'] != binding or saved['commands'] != commands:
            raise ImageBuildError('verification inputs changed')
        if result['outputs'] != inventory(folder / 'output') or result['policy'] != builder._policy():
            raise ImageBuildError('verified outputs or execution policy changed')
        builder._release_resources(folder)
        discard_work(folder, ('root', 'source'), {'prepared': saved, 'result': result}, apply=True)
        return result
    if saved != {'root': inventory(folder / 'root'), 'binding': binding, 'commands': commands}:
        raise ImageBuildError('verification inputs changed')
    if complete.exists():
        result = json.loads(complete.read_text())
        if result['outputs'] != inventory(folder / 'output') or result['policy'] != builder._policy():
            raise ImageBuildError('verified outputs or execution policy changed')
    else:
        for index, command in enumerate(commands):
            write_json(folder / f'command-{index}.view.json', {'schema':1, 'attempt_id':folder.name,
                'stage_id':folder.name, 'package':None, 'phase':'verify', 'command_index':index,
                'command':command, 'checkpoint':f'command-{index}.controller.json'})
            from ..verification_observations import capture as capture_observation
            try:
                builder.runner.run(folder / 'root', folder / 'source', folder / 'output', command, {}, folder / f'command-{index}.log')
            except Exception as error:
                capture_observation(builder, folder, saved, index, error)
                raise
            capture_observation(builder, folder, saved, index)
        sync_tree(folder / 'output')
        result = {'outputs': inventory(folder / 'output'), 'policy': builder._policy()}
        write_json(complete, result)
    builder._release_resources(folder)
    discard_work(folder, ('root', 'source'), {'prepared': saved, 'result': result}, apply=True)
    return result


def run(project, catalogue, controller):
    project, catalogue = Path(project).resolve(), Path(catalogue).resolve()
    state = project / 'state'
    work = state / 'image-build' / 'seed-bootstrap'
    attempts = state / 'image-build' / 'attempts'
    ensure_directory(work)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        runner = configured_runner(controller, state)
        recipe = catalogue / 'm4/stages/native-seed'
        recipes = work / 'recipes'
        if not recipes.exists():
            ensure_directory(recipes)
        if not (recipes / 'm4').exists():
            shutil.copytree(recipe, recipes / 'm4')
            sync_tree(recipes)
        elif inventory(recipe) != inventory(recipes / 'm4'):
            raise ImageBuildError('M4 recipe changed; retained operation must keep its original inputs')
        builder = ImageBuild(package_dir=recipes, state_dir=state, runner=runner)
        intent_path = work / 'operation.json'
        binding = {'catalogue': inventory(catalogue), 'policy': builder._policy(), 'recipe': inventory(recipe)}
        if intent_path.exists():
            operation = json.loads(intent_path.read_text())
            if operation['binding'] != binding:
                raise ImageBuildError('seed operation inputs changed')
        else:
            operation = {'schema': 1, 'binding': binding, 'phase': 'assembly'}
            write_json(intent_path, operation)
        logging.info('Assembling or reusing recorded distribution seed')
        seed = prepare(catalogue, work / 'assembly', user_id=runner.execute.execution_user_id,
                       group_id=runner.execute.execution_group_id)
        logging.info('Verifying seed through box-control')
        verify(builder, attempts / 'seed-verification', work / 'assembly/root', [['/bin/bash', '-c', PROBE]], identity(seed))
        selection = builder.import_bootstrap(work / 'assembly/root',
            {'distribution_seed': seed['discovery'], 'file_provenance': seed['provenance'],
             'verification': identity(json.loads((attempts / 'seed-verification/verification.json').read_text()))})
        operation.update(phase='source-build', seed_generation=selection.generation)
        write_json(intent_path, operation)
        logging.info('Building or resuming GNU M4 from source')
        # The seed-operation lock owns this project run. Recover even if the
        # caller died before copying the new pipeline identity into operation.json.
        pipelines = list((state / 'image-build/pipelines').glob('*/pipeline.json'))
        matches = [p for p in pipelines if json.loads(p.read_text())['operation'] == 'seed-check'
                   and json.loads(p.read_text())['arguments'].get('targets') == ['m4']
                   and json.loads(p.read_text())['selection'] == str(selection.root.parent)
                   and json.loads(p.read_text())['recipes'] == inventory(recipes)]
        if len(matches) > 1:
            raise ImageBuildError('ambiguous M4 pipelines; inspect retained state')
        if matches:
            result = builder.resume(matches[0].parent.name)
        else:
            result = builder.verify_seed(['m4'], host_bootstrap=selection)
        operation.update(phase='verify-m4', m4_generation=result.generation)
        write_json(intent_path, operation)
        # Fresh root contains the seed runtime, with its M4 replaced by the
        # recorded source output. It never reuses the compiler's build directory.
        fresh = work / 'm4-runtime'
        marker = work / 'm4-runtime.json'
        expected = {'seed': selection.generation, 'm4': result.generation}
        if not marker.exists():
            if fresh.exists(): discard_staging(fresh)
            shutil.copytree(selection.root, fresh, symlinks=True)
            source = result.root / 'usr/bin/m4'
            target = fresh / 'usr/bin/m4'
            target.unlink()
            shutil.copy2(source, target)
            sync_tree(fresh)
            write_json(marker, {'inputs': expected, 'root': inventory(fresh)})
        if json.loads(marker.read_text()) != {'inputs': expected, 'root': inventory(fresh)}:
            raise ImageBuildError('M4 verification root changed')
        commands = [['/bin/bash', '-c', "set -eu; /usr/bin/m4 --version | grep '1.4.21'; printf 'eval(6*7)\\n' | /usr/bin/m4 | grep -x 42"]]
        verify(builder, attempts / 'm4-verification', fresh, commands, expected)
        operation.update(phase='complete')
        write_json(intent_path, operation)
        return {'seed_generation': selection.generation, 'm4_generation': result.generation,
                'operation': str(intent_path), 'status': 'complete'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--controller-config', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from ..box_control_adapter import BuildExecutionPending
    try:
        result = run(args.project, args.package_dir, args.controller_config)
    except BuildExecutionPending:
        print(json.dumps({'status': 'pending', 'resume': 'repeat the same command'}))
        raise SystemExit(75)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
