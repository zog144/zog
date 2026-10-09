"""Build reviewed GCC prerequisites and GCC through the dependency resolver."""
import argparse
import fcntl
import json
import logging
from pathlib import Path
from zog.image_build import ImageBuild, read_selection
from zog.image_build.configuration import configured_runner
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory, write_json
from zog.image_build.final_compiler import replacement_records
from zog.image_build.glibc_final import wait_for
from zog.image_build.native import pipeline
from zog.image_build.stages import stage_recipes


def run(project, catalogue, controller, selection, ownership, work, superseded):
    project, catalogue, work = (Path(x).resolve() for x in (project, catalogue, work))
    state = project/'state'
    work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base = read_selection(selection)
        old = replacement_records(ownership)
        plan = stage_recipes(catalogue.parent/'bootstrap/lfs-final-gcc.py', catalogue, work/'recipes')
        runner = configured_runner(controller, state)
        builder = ImageBuild(package_dir=work/'recipes', state_dir=state, runner=runner,
                             maximum_generations=32, dependency_replacements={'gawk-final': old})
        binding = {'base':base.generation, 'recipes':inventory(work/'recipes'),
                   'policy':builder._policy(), 'superseded':superseded}
        intent = work/'intent.json'
        if intent.exists() and json.loads(intent.read_text()) != binding:
            raise ImageBuildError('GCC dependency continuation inputs changed')
        write_json(intent, binding)
        try:
            prior_builder = ImageBuild(package_dir=work/'recipes', state_dir=state, runner=runner)
            previous = prior_builder.inspect_pipeline(superseded)
            if previous['selection'] != str(base.root.parent) or set(previous['arguments']['targets']) not in ({'gcc-final'}, set(plan['targets'])):
                raise ImageBuildError('superseded pipeline differs from intended GCC failure')
            if previous['status'] not in ('pending','released'):
                raise ImageBuildError('superseded GCC pipeline must be stopped pending or released')
            if previous['policy'] == builder._policy(): prior_builder = builder
            if previous['status'] != 'released': prior_builder.release_pipeline(superseded)
            result = wait_for(work, 'gcc-dependencies', lambda: pipeline(builder,base,plan['targets'],'native-check'))
            record = {'phase':'complete','outputs_generation':result.generation,'base':base.generation,
                      'self_hosted':False,'remaining':'Compose final GCC and Gawk, run installed acceptance and M4 rebuild'}
            write_json(work/'result.json',record)
            return record
        except Exception as error:
            write_json(work/'result.json',{'phase':'failed','error':str(error),'self_hosted':False})
            raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','catalogue','controller','selection','ownership','work','superseded'):
        parser.add_argument('--'+name, required=True)
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(**vars(parser.parse_args()))), flush=True)
