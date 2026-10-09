"""Explicitly import completed outputs from released pipelines for verified reuse."""
import json
import shutil
import uuid
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import inventory, ensure_directory, write_json, sync_tree, sync_directory, discard_staging
from .metadata import identity, load_packages
from .cleanup import released, checked_tree


def key(inputs, policy):
    return identity({'inputs': inputs, 'policy': policy})


def validate(directory, inputs, policy):
    record = json.loads((directory/'record.json').read_text())
    result = record['result']
    if record['policy'] != policy or result['inputs'] != inputs:
        raise ImageBuildError('cached package input or policy mismatch')
    if result['outputs'] != inventory(directory/'output'):
        raise ImageBuildError('cached package outputs changed')
    if result['identity'] != identity({'inputs': inputs, 'outputs': result['outputs']}):
        raise ImageBuildError('cached package identity mismatch')
    return record


def import_completed(builder, pipeline_id):
    """Retain immutable copies; incomplete packages are never candidates."""
    with builder.locked():
        pipeline = builder.inspect_pipeline(pipeline_id)
        if not pipeline.get('released') or pipeline['status'] != 'released':
            raise ImageBuildError('artifact import requires an explicitly released pipeline')
        policy = builder._policy()
        if pipeline['policy'] != policy:
            raise ImageBuildError('artifact import execution policy changed')
        recipes = builder._pipeline_directory(pipeline_id)/'package'
        if inventory(recipes) != pipeline['recipes']:
            raise ImageBuildError('artifact import recipe snapshot changed')
        packages = load_packages(recipes)
        store = builder.state/'image-build/package-artifacts'; ensure_directory(store)
        imported = []
        for name in pipeline['attempts'].values():
            if Path(name).name != name or name in ('.','..'):
                raise ImageBuildError('invalid artifact attempt identity')
            attempt = builder.state/'image-build/attempts'/name
            for folder in sorted((attempt/'packages').glob('*')):
                if not (folder/'result.json').exists(): continue
                released(folder)
                result = json.loads((folder/'result.json').read_text())
                inputs = result['inputs']
                if inputs['package'] != packages[folder.name].fingerprint:
                    raise ImageBuildError('artifact recipe fingerprint differs')
                if result['outputs'] != inventory(folder/'output') or result['identity'] != identity({'inputs': inputs, 'outputs': result['outputs']}):
                    raise ImageBuildError('artifact source outputs changed')
                if builder.provenance:
                    pointer = folder/'provenance.json'
                    if pointer.exists():
                        binding = builder.provenance.finish(folder, result=result)
                        reference = {k: binding[k] for k in ('output', 'result')}
                    elif 'provenance' in result:
                        reference = result['provenance']
                    else:
                        if any((folder / f'provenance-{phase}.json').exists() for phase in ('preparing', 'finalizing')):
                            raise ImageBuildError('known package provenance pointer is missing')
                        reference = builder.provenance.legacy_output(folder.name, result)
                    builder.provenance.verify_output(reference, folder.name, result)
                    result = dict(result, provenance=reference)
                target = store/key(inputs, policy)
                if target.exists():
                    if validate(target, inputs, policy)['result'] != result:
                        raise ImageBuildError('ambiguous outputs for identical artifact inputs')
                else:
                    pending = store/('pending-'+uuid.uuid4().hex)
                    ensure_directory(pending)
                    try:
                        shutil.copytree(folder/'output', pending/'output', symlinks=True)
                        write_json(pending/'record.json', {'schema':1,'result':result,'policy':policy,'origin_pipeline':pipeline_id,'origin_package':str(folder)})
                        validate(pending, inputs, policy);sync_tree(pending)
                        pending.rename(target);sync_directory(store)
                    finally:
                        if pending.exists():discard_staging(pending)
                imported.append({'package':folder.name,'artifact':target.name,'identity':result['identity']})
        return {'pipeline':pipeline_id,'imported':imported}


def restore(builder, inputs, destination):
    policy = builder._policy()
    artifact = builder.state/'image-build/package-artifacts'/key(inputs, policy)
    if not artifact.exists(): return False
    record = validate(artifact, inputs, policy)
    if builder.provenance:
        reference = record['result'].get('provenance')
        if reference is None:
            # A legacy cache can only lack provenance if its recorded policy did.
            if (record.get('policy') or {}).get('provenance'):
                raise ImageBuildError('cached provenance binding is missing')
        else:
            builder.provenance.verify_output(reference, destination.name, record['result'])
    if destination.exists():
        raise ImageBuildError('unrecorded workspace blocks artifact restoration')
    pending = destination.parent.parent/'artifact-restoration'/destination.name
    if pending.exists():checked_tree(pending);discard_staging(pending)
    ensure_directory(pending)
    try:
        shutil.copytree(artifact/'output', pending/'output', symlinks=True)
        write_json(pending/'artifact-reuse.json', {'artifact':artifact.name,'origin_pipeline':record['origin_pipeline'],'origin_package':record['origin_package'],'identity':record['result']['identity']})
        write_json(pending/'result.json', record['result']);sync_tree(pending)
        ensure_directory(destination.parent)
        pending.rename(destination);sync_directory(destination.parent)
    finally:
        if pending.exists():checked_tree(pending);discard_staging(pending)
    return True
