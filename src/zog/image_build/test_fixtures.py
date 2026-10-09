"""Declared pre-test roots with separate immutable controller registrations."""
import json
import shutil
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import digest,write_json
from .metadata import relative,identity
from .stages import recorded_root


def controller_preparation(directory):
    """Expose the exact recorded root through the runner's manifest contract."""
    directory=Path(directory)
    record=json.loads((directory/'root.json').read_text())
    path=directory/'prepared.json'
    if path.exists():
        if json.loads(path.read_text())!=record:
            raise ImageBuildError('fixture controller preparation changed')
    else:
        write_json(path,record)


def prepare(builder,package,directory):
    directory=Path(directory);spec=package.integration['test_fixtures']
    config=builder.runner.execute.configuration()
    if (config.get('execution_user_id')!=spec['execution_user_id'] or
        config.get('execution_group_id')!=spec['execution_group_id'] or
        config.get('device_profile')!=spec['device_profile'] or
        config.get('resource_limits',{}).get('thread-count-maximum',0)<spec['thread_count_maximum']):
        raise ImageBuildError('controller policy does not satisfy declared test fixtures')
    if spec['schema']!=1:raise ImageBuildError('unsupported fixture schema')
    cache_keys={'cache_command','cache_artifact','cache_destination'}
    supplied=cache_keys.intersection(spec)
    if supplied and supplied!=cache_keys:
        raise ImageBuildError('incomplete fixture cache specification')
    source=directory/'source';output=directory/'output';original=directory/'root'
    binding={'package':package.fingerprint,'spec':spec,'prepared':json.loads((directory/'prepared.json').read_text()),'policy':config}
    # Never mutate a registered root; complete/release prior command resources first.
    builder._release_resources(directory)
    cache_dir=directory/'test-fixture-cache';cache_dir.mkdir(exist_ok=True)
    (cache_dir/'output').mkdir(exist_ok=True)
    def fixtures(root):
        shutil.copytree(original,root,symlinks=True)
        for name,contents in spec['files'].items():
            path=root/relative(name)
            if any((root/p).is_symlink() for p in Path(name).parents) or path.is_symlink():
                raise ImageBuildError('fixture path traverses a symlink')
            if path.exists() and not path.is_file():raise ImageBuildError('fixture replaces non-file')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(contents);path.chmod(0o644)
    cache_root=recorded_root(cache_dir/'root',identity(binding),fixtures)
    controller_preparation(cache_dir)
    if not supplied:
        return cache_root,cache_dir
    command=spec['cache_command']
    write_json(cache_dir/'cache-0.view.json',{'schema':1,'attempt_id':directory.parent.parent.name,
        'stage_id':package.integration.get('stage_id','package-build'),'package':package.integration.get('project',package.name),
        'pipeline_id':getattr(builder,'_pipeline_record',{}).get('pipeline_id') if getattr(builder,'_pipeline_record',None) else None,
        'phase':'test-fixture-cache','command_index':0,'command':command,'checkpoint':'cache-0.controller.json'})
    builder.runner.run(cache_root,source,cache_dir/'output',command,package.environment,cache_dir/'cache-0.log')
    builder._release_resources(cache_dir)
    cache=cache_dir/'output'/relative(spec['cache_artifact'])
    if not cache.is_file() or cache.is_symlink() or cache.stat().st_size==0:raise ImageBuildError('missing generated loader cache')
    runtime=directory/'test-fixture-runtime';runtime.mkdir(exist_ok=True)
    def cached(root):
        shutil.copytree(cache_root,root,symlinks=True)
        target=root/relative(spec['cache_destination'])
        if target.is_symlink() or any((root/p).is_symlink() for p in Path(spec['cache_destination']).parents):
            raise ImageBuildError('cache destination traverses a symlink')
        if target.exists():target.unlink()
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cache,target);target.chmod(0o644)
    root=recorded_root(runtime/'root',{'fixtures':identity(binding),'cache':digest(cache)},cached)
    controller_preparation(runtime)
    return root,runtime


def release(builder,directory):
    for name in ('test-fixture-cache','test-fixture-runtime'):
        folder=Path(directory)/name
        if folder.exists():builder._release_resources(folder)


def cleanup(directory,*,apply):
    from .cleanup import discard_work
    removed=[]
    for name in ('test-fixture-cache','test-fixture-runtime'):
        folder=Path(directory)/name
        if folder.exists():
            binding=json.loads((folder/'root.json').read_text())
            removed+=discard_work(folder,('root',),binding,apply=apply)
    return removed
