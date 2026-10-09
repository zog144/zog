from pathlib import Path
import platform
import pytest
from zog.image_build.engine import ImageBuildError
from zog.image_build.filesystem import inventory,merge
from zog.image_build.native import remove_owned
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages,order
from test_source_build import prepared

def test_native_validation_does_not_promote_or_activate(prepared):
    b,runner,seed,toolchain=prepared
    native=b._publish(toolchain.root,{'kind':'native-temporary-toolchain','architecture':platform.machine(),'outputs':inventory(toolchain.root)},'native-temporary-toolchain',{'self_hosted':False})
    with pytest.raises(ImageBuildError,match='promoted second-stage'):
        b._ensure(['consumer'],toolchain=native)
    result=b.verify_native(['consumer'],toolchain=native)
    assert result.manifest['kind']=='native-check'
    assert not native.manifest['self_hosted']
    assert not (b.state/'image-build/active').exists()
    count=len(runner.calls)
    p=next(p for p in (b.state/'image-build/pipelines').glob('*/pipeline.json') if 'native-check' in p.read_text())
    assert b.resume(p.parent.name).generation==result.generation
    assert len(runner.calls)==count

def test_owned_replacement_checks_all_files_before_removal(tmp_path):
    old=tmp_path/'old';(old/'sysroot/usr/bin').mkdir(parents=True)
    (old/'sysroot/usr/bin/bash').write_text('old');(old/'sysroot/usr/bin/sh').symlink_to('bash')
    records=inventory(old);root=tmp_path/'root';merge(old/'sysroot',root)
    (root/'usr/bin/bash').write_text('changed')
    with pytest.raises(ImageBuildError,match='changed'):remove_owned(root,records)
    assert (root/'usr/bin/sh').is_symlink()
    (root/'usr/bin/bash').write_text('old');(root/'usr/bin/unrelated').write_text('keep')
    remove_owned(root,records)
    assert not (root/'usr/bin/bash').exists() and not (root/'usr/bin/sh').is_symlink()
    assert (root/'usr/bin/unrelated').read_text()=='keep'

def test_native_stage_graph(tmp_path):
    root=Path(__file__).parents[1]/'project'
    stage_recipes(root/'bootstrap/lfs-native-temporary.py',root/'package',tmp_path/'recipes')
    p=load_packages(tmp_path/'recipes')
    assert order(p,['gcc-native-temporary'])==('binutils-native-temporary','gcc-native-temporary')

@pytest.mark.parametrize("kind", ["native-final-libc", "native-compiler-candidate"])
def test_final_libc_requires_acceptance_and_architecture(prepared, kind):
    b,runner,seed,toolchain=prepared
    inputs={'kind':kind,'architecture':platform.machine(),'outputs':inventory(toolchain.root),'verification':'recorded-probe'}
    attrs={'source_built':True,'build_environment_complete':True,'self_hosted':False,
           'verification_execution':{'exit_code':0,'cleanup_complete':True}}
    accepted=b._publish(toolchain.root,inputs,kind,attrs)
    assert b.verify_native(['consumer'],toolchain=accepted).manifest['kind']=='native-check'
    with pytest.raises(ImageBuildError,match='second-stage'):b._ensure(['consumer'],toolchain=accepted)
    bad=b._publish(toolchain.root,dict(inputs,verification=None),kind,attrs)
    with pytest.raises(ImageBuildError,match='acceptance'):b._ensure(['consumer'],toolchain=bad,native_check=True)
    wrong=b._publish(toolchain.root,dict(inputs,architecture='wrong'),kind,attrs)
    with pytest.raises(ImageBuildError,match='architecture'):b._ensure(['consumer'],toolchain=wrong,native_check=True)


def test_arithmetic_stage_dependencies(tmp_path):
    root=Path(__file__).parents[1]/'project'
    stage_recipes(root/'bootstrap/lfs-final-math.py',root/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    assert order(packages,['mpc-final'])==('gmp-final','mpfr-final','mpc-final')
    assert order(packages,['mpc-final'],runtime_only=True)==('gmp-final','mpfr-final','mpc-final')
    for p in packages.values():
        assert p.steps['test'] and 'make -j1 check' in p.steps['test'][0][-1]


def test_released_pipeline_does_not_block_new_graph(tmp_path):
    import json
    from types import SimpleNamespace
    from zog.image_build.native import pipeline
    recipes=tmp_path/'recipes';recipes.mkdir()
    state=tmp_path/'state';old=state/'image-build/pipelines/old';old.mkdir(parents=True)
    selection=SimpleNamespace(root=tmp_path/'generation/root')
    (old/'pipeline.json').write_text(json.dumps({'released':True,'operation':'native-check','selection':str(selection.root.parent),'recipes':[],'arguments':{'targets':['target']}}))
    b=SimpleNamespace(state=state,package_dir=recipes,verify_native=lambda targets,toolchain:'new')
    assert pipeline(b,selection,['target'],'native-check')=='new'
