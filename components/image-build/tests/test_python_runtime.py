import json
from pathlib import Path
import pytest
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory
from zog.image_build.metadata import identity, load_packages, order
from zog.image_build.python_runtime import assemble, ownership, PROBE
from zog.image_build.stages import stage_recipes

ROOT=Path(__file__).parents[1]/'project'

def test_runtime_graph_freezes_new_sources_and_preserves_bootstrap(tmp_path):
    plan=stage_recipes(ROOT/'bootstrap/python-runtime.py',ROOT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    resolved=order(packages,plan['targets'])
    assert resolved[-1]=='python-final'
    assert set(resolved[:-1])=={'libffi-final','expat-final','gdbm-final','pkgconf-final'}
    for package in packages.values():
        assert package.licensing['source']['sha256']==package.sources[0]['sha256']
    assert packages['python-final'].licensing['version']=='3.15.0rc2'
    import ast
    old=ast.literal_eval((ROOT/'package/python/stages/native-environment/sources.py').read_text())
    assert '3.14.7' in old[0]['url']

def fixture(tmp_path):
    base=tmp_path/'base';(base/'usr/bin').mkdir(parents=True)
    (base/'usr/bin/python3').write_text('old python')
    records=inventory(base)
    old={'inputs':{'package':'fixture'},'outputs':records}
    old['identity']=identity(old)
    manifest=tmp_path/'old.json';manifest.write_text(json.dumps({'packages':{'python-native-environment':old}}))
    addition=tmp_path/'addition';(addition/'usr/bin').mkdir(parents=True)
    (addition/'usr/bin/python3').write_text('new python')
    return base,addition,manifest

def test_replacement_checks_previous_bytes_and_preserves_unowned_files(tmp_path):
    base,addition,manifest=fixture(tmp_path)
    (base/'usr/bin/unrelated').write_text('retained')
    assemble(tmp_path/'out',base,addition,ownership(manifest))
    assert (tmp_path/'out/usr/bin/python3').read_text()=='new python'
    assert (tmp_path/'out/usr/bin/unrelated').read_text()=='retained'

def test_changed_previous_python_is_not_overwritten(tmp_path):
    base,addition,manifest=fixture(tmp_path)
    (base/'usr/bin/python3').write_text('unexpected bytes')
    with pytest.raises(ImageBuildError,match='replacement input changed'):
        assemble(tmp_path/'out',base,addition,ownership(manifest))

def test_unowned_collision_is_not_overwritten(tmp_path):
    base,addition,manifest=fixture(tmp_path)
    (base/'usr/bin/unrelated').write_text('retained')
    (addition/'usr/bin/unrelated').write_text('collision')
    with pytest.raises(ImageBuildError,match='ownership conflict'):
        assemble(tmp_path/'out',base,addition,ownership(manifest))

def test_tampered_ownership_rejected(tmp_path):
    _,_,manifest=fixture(tmp_path)
    value=json.loads(manifest.read_text());value['packages']['python-native-environment']['outputs']=[]
    manifest.write_text(json.dumps(value))
    with pytest.raises(ImageBuildError,match='ownership identity changed'):ownership(manifest)

def test_probe_is_valid_python():
    compile(PROBE,'installed-python-probe','exec')

@pytest.mark.parametrize('inputs,details', [
    ({'architecture':'x86_64'}, {'stage':2,'self_hosted':True}),
    ({'kind':'toolchain'}, {'stage':2,'self_hosted':True}),
    ({'kind':'toolchain','stage':2}, {'stage':1,'self_hosted':True}),
])
def test_invalid_generation_contract_is_rejected_before_publication(tmp_path, inputs, details):
    from zog.image_build import ImageBuild
    builder=ImageBuild(package_dir=tmp_path/'recipes',state_dir=tmp_path/'state')
    root=tmp_path/'root';root.mkdir();(root/'file').write_text('payload')
    with pytest.raises(ImageBuildError,match='publication .* mismatch'):
        builder._publish(root,inputs,'toolchain',details)
    store=tmp_path/'state/image-build/generations'
    assert not store.exists() or not list(store.iterdir())

def test_runtime_generation_round_trips_strict_reader(tmp_path):
    from zog.image_build import ImageBuild, read_selection
    builder=ImageBuild(package_dir=tmp_path/'recipes',state_dir=tmp_path/'state')
    root=tmp_path/'root';root.mkdir();(root/'file').write_text('payload')
    result=builder._publish(root,{'kind':'toolchain','stage':2,'libraries':'fixture'},'toolchain',{'stage':2,'self_hosted':True})
    assert read_selection(result.root.parent).generation==result.generation


@pytest.mark.parametrize('exception_index', range(5))
def test_services_fixture_and_exception_are_exact_and_source_bound(tmp_path, exception_index):
    import shlex
    from zog.image_build.python_runtime import reviewed_exceptions
    stage_recipes(ROOT/'bootstrap/python-runtime.py',ROOT/'package',tmp_path/'recipes')
    package=load_packages(tmp_path/'recipes')['python-final']
    spec=package.integration['test_fixtures']
    assert set(spec['files'])=={'etc/services'}
    assert 'domain 53/tcp' in spec['files']['etc/services']
    assert 'domain 53/udp' in spec['files']['etc/services']
    exceptions=reviewed_exceptions(package)
    assert [e['selector'] for e in exceptions]==['test.test_socket.RDSTest.'+name for name in ['testPeek','testSelect','testSendAndRecv','testSendAndRecvMsg','testSendAndRecvMulti']]
    command=package.steps['test'][1][-1]
    args=shlex.split(command)
    assert [args[i+1] for i, arg in enumerate(args) if arg=='--ignore']==[e['selector'] for e in exceptions]
    assert args.count('--ignore')==5 and 'test_socket' in args
    probe=package.steps['test'][0][-1].split("<<'ZOG_SOCKET_PROBE'\n", 1)[1].rsplit('ZOG_SOCKET_PROBE', 1)[0]
    compile(probe, 'socket-probe', 'exec')
    assert 'range(100)' in probe and 'return original(self)' in probe
    assert 'result.testsRun != 500 or result.skipped' in probe
    assert 'getTestCaseNames(socket_tests.RDSTest) == expected' in probe
    assert all('BasicRDSTest' not in e['selector'] for e in exceptions)
    exceptions[exception_index]['source_sha256']='0'*64
    with pytest.raises(ImageBuildError,match='requires review'):
        reviewed_exceptions(package)
