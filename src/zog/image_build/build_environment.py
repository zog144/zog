"""Expand a recorded native temporary toolchain using reviewed stage dependencies."""
import fcntl,json,platform,shutil
from pathlib import Path
from .engine import ImageBuild,read_selection
from .configuration import configured_runner
from .filesystem import inventory,merge,write_json,ensure_directory,discard_staging
from .stages import stage_recipes,recorded_root
from .native import pipeline
from .developer.seed_build import verify
from .metadata import names,literal
from .errors import ImageBuildError


def run(project,catalogue,controller,selection,operation_name='native-build-environment-pass1'):
    names([operation_name]);project=Path(project).resolve();catalogue=Path(catalogue).resolve()
    state=project/'state';work=state/'image-build'/operation_name;ensure_directory(work)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        plan=stage_recipes(catalogue.parent/'bootstrap/lfs-native-environment.py',catalogue,work/'recipes')
        commands=literal(catalogue.parent/'bootstrap/native-environment-checks.py')
        base=read_selection(selection)
        if base.manifest['kind']!='native-temporary-toolchain' or not base.manifest.get('source_built'):
            raise ImageBuildError('source-built native temporary toolchain required')
        builder=ImageBuild(package_dir=work/'recipes',state_dir=state,runner=configured_runner(controller,state),maximum_generations=16)
        intent={'base':base.generation,'plan':plan,'recipes':inventory(work/'recipes'),'commands':commands,'policy':builder._policy(),'maximum_generations':16}
        record=work/'operation.json'
        saved=json.loads(record.read_text()) if record.exists() else {'schema':1,'phase':'build','intent':intent}
        if saved['intent']!=intent:raise ImageBuildError('native environment operation inputs changed')
        write_json(record,saved)
        root=work/'assembled-root'
        def cleanup():
            if root.exists():discard_staging(root)
            write_json(work/'assembly-cleanup.json',{'phase':'complete'})
        if saved['phase']=='complete':
            read_selection(state/'image-build/generations'/saved['generation']);cleanup();return saved
        built=pipeline(builder,base,plan['targets'],'native-check')
        saved.update(phase='verify',packages_generation=built.generation);write_json(record,saved)
        def prepare(destination):
            shutil.copytree(base.root,destination,symlinks=True)
            merge(built.root,destination,preserve_existing_directories=True)
        recorded_root(root,{'base':base.generation,'packages':built.generation},prepare)
        verify(builder,state/'image-build/attempts'/(operation_name+'-verification'),root,commands,{'base':base.generation,'packages':built.generation})
        with builder.locked():
            result=builder._publish(root,{'schema':2,'kind':'native-temporary-toolchain','base':base.generation,'packages':built.generation,'outputs':inventory(root),'architecture':platform.machine()},'native-temporary-toolchain',{'source_built':True,'self_hosted':False,'build_environment_complete':True,'lfs_edition':plan['lfs_edition']})
        saved.update(phase='complete',generation=result.generation);write_json(record,saved);cleanup();return saved
