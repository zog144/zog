from pathlib import Path
import ast
import pytest
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages,order
from zog.image_build.errors import ImageBuildError

PROJECT=Path(__file__).parents[1]/'project'

def test_environment_graph_links_python_libraries_and_texinfo_perl(tmp_path):
    plan=stage_recipes(PROJECT/'bootstrap/lfs-native-environment.py',PROJECT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    python=order(packages,['python-native-environment'])
    assert set(python)=={'zlib-native-environment','mpdecimal-native-environment','python-native-environment'}
    assert python[-1]=='python-native-environment'
    assert order(packages,['texinfo-native-environment'])==('perl-native-environment','texinfo-native-environment')
    assert len(order(packages,plan['targets']))==8
    for package in packages.values():
        assert all(len(s['sha256'])==64 and s['url'].startswith('https://') for s in package.sources)
        assert package.integration['stage_id']=='native-environment'

def test_environment_snapshot_rejects_recipe_mutation(tmp_path):
    plan=PROJECT/'bootstrap/lfs-native-environment.py';destination=tmp_path/'recipes'
    stage_recipes(plan,PROJECT/'package',destination)
    target=destination/'python-native-environment/build.py'
    data=ast.literal_eval(target.read_text());data['build']=[['/bin/false']];target.write_text(repr(data))
    with pytest.raises(ImageBuildError,match='recipe changed'):
        stage_recipes(plan,PROJECT/'package',destination)

from test_source_build import prepared
from zog.image_build.filesystem import inventory
import platform

def test_environment_completed_resume_and_seed_rejection(prepared, monkeypatch):
    import zog.image_build.build_environment as environment
    b,runner,seed,toolchain=prepared
    project=b.state.parent
    monkeypatch.setattr(environment,'configured_runner',lambda *args:runner)
    with pytest.raises(ImageBuildError,match='source-built native'):
        environment.run(project,PROJECT/'package','unused',seed.root.parent)
    native=b._publish(toolchain.root,{'kind':'native-temporary-toolchain','architecture':platform.machine(),'outputs':inventory(toolchain.root)},'native-temporary-toolchain',{'source_built':True,'self_hosted':False})
    outputs=b._publish(seed.root,{'kind':'native-check','architecture':platform.machine(),'outputs':inventory(seed.root)},'native-check',{})
    calls=[]
    monkeypatch.setattr(environment,'pipeline',lambda *args:(calls.append('build') or outputs))
    monkeypatch.setattr(environment,'verify',lambda *args:calls.append('verify'))
    first=environment.run(project,PROJECT/'package','unused',native.root.parent)
    assert first['phase']=='complete' and calls==['build','verify']
    assert not (b.state/'image-build/native-build-environment-pass1/assembled-root').exists()
    assert environment.run(project,PROJECT/'package','unused',native.root.parent)==first
    assert calls==['build','verify']
    original=environment.literal
    monkeypatch.setattr(environment,'literal',lambda path:[['/bin/false']] if path.name=='native-environment-checks.py' else original(path))
    with pytest.raises(ImageBuildError,match='inputs changed'):
        environment.run(project,PROJECT/'package','unused',native.root.parent)
