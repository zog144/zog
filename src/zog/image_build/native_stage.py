"""Run an explicit native-stage plan without historical host-specific drivers."""
import argparse
import fcntl
import json
from pathlib import Path

from .box_control_adapter import BuildExecutionPending
from .configuration import configured_runner
from .engine import ImageBuild, read_selection
from .filesystem import inventory, write_json
from .native import pipeline
from .stages import stage_recipes


def run(project, catalogue, plan, controller, selection, work):
    project, catalogue, plan, controller, selection, work = (
        Path(p).resolve() for p in (project, catalogue, plan, controller, selection, work))
    work.mkdir(parents=True, exist_ok=True)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = read_selection(selection)
        if not selected.manifest.get('build_environment_complete') or not selected.manifest.get('source_built'):
            raise ValueError('Native stage requires a source-built complete build environment')
        stage = stage_recipes(plan, catalogue, work / 'recipes')
        builder = ImageBuild(package_dir=work / 'recipes', state_dir=project / 'state',
            runner=configured_runner(controller, project / 'state'), maximum_generations=16)
        intent = {'project': str(project), 'base': selected.generation, 'plan': stage,
            'recipes': inventory(work / 'recipes'), 'policy': builder._policy(),
            'controller': json.loads(controller.read_text())}
        record = work / 'operation.json'
        saved = json.loads(record.read_text()) if record.exists() else {
            'schema': 1, 'phase': 'running', 'intent': intent}
        if saved['intent'] != intent:
            raise ValueError('Recorded native-stage inputs changed')
        if saved['phase'] == 'complete':
            read_selection(project / 'state/image-build/generations' / saved['generation'])
            return saved
        if saved['phase'] == 'failed':
            raise ValueError('Failed operation requires explicit review; no automatic retry')
        write_json(record, saved)
        try:
            result = pipeline(builder, selected, stage['targets'], 'native-check')
        except BuildExecutionPending as pending:
            saved.update(phase='running', job_id=pending.job_id)
            write_json(record, saved)
            raise
        except Exception as error:
            saved.update(phase='failed', error=str(error))
            write_json(record, saved)
            raise
        saved.update(phase='complete', generation=result.generation, self_hosted=False)
        write_json(record, saved)
        return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'catalogue', 'plan', 'controller', 'selection', 'work'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = run(**vars(args))
    except BuildExecutionPending:
        print(json.dumps({'status': 'pending', 'resume': 'repeat the same command'}))
        raise SystemExit(75)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
