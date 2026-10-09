from pathlib import Path
from dataclasses import asdict, replace
import pytest
from zog.image_build import ImageBuild, ImageBuildError, load_package
from zog.image_build.metadata import order, identity, load_packages
from zog.image_build.stages import stage_recipes
from test_source_build import recipe, RecordingRunner


def test_test_dependency_is_built_and_mounted_but_not_runtime_output(tmp_path):
    packages = tmp_path / 'packages'
    recipe(packages, 'test-library')
    recipe(packages, 'test-tool', runtime=('test-library',))
    original = recipe(packages, 'consumer')
    old = asdict(original); old.pop('licensing'); old.pop('test_dependencies'); old.pop('recipe_directory'); old.pop('source_provenance')
    assert original.fingerprint == identity(old)
    (packages/'consumer/dependencies.py').write_text(repr(dict(build=[], runtime=[], test=['test-tool'])))
    consumer = load_package(packages/'consumer')
    assert consumer.fingerprint != original.fingerprint
    runner = RecordingRunner()
    builder = ImageBuild(package_dir=packages, state_dir=tmp_path/'state', runner=runner)
    host = tmp_path/'host'; host.mkdir(); (host/'seed').write_text('seed')
    seed = builder.import_bootstrap(host, {'id':'test'})
    result = builder.verify_seed(['consumer'], host_bootstrap=seed)
    commands = [args for args, _ in runner.calls]
    assert commands.index(['install','test-tool']) < commands.index(['compile','consumer'])
    for args, paths in runner.calls:
        if args == ['test','consumer']:
            assert 'usr/share/test-tool' in paths
            assert 'usr/share/test-library' in paths
    assert (result.root/'usr/share/consumer').exists()
    assert not (result.root/'usr/share/test-tool').exists()


def test_test_edges_detect_missing_definitions_and_cycles(tmp_path):
    package = recipe(tmp_path, 'consumer')
    package = replace(package, test_dependencies=('missing',))
    with pytest.raises(ImageBuildError, match='missing reviewed'):
        order({'consumer':package}, ['consumer'])
    cyclic = replace(package, test_dependencies=('consumer',))
    with pytest.raises(ImageBuildError, match='cycle'):
        order({'consumer':cyclic}, ['consumer'])
    assert order({'consumer':package}, ['consumer'], runtime_only=True) == ('consumer',)


def test_binutils_graph_materializes_support_packages(tmp_path):
    root = Path(__file__).parents[1]/'project'
    plan = stage_recipes(root/'bootstrap/lfs-final-binutils.py', root/'package', tmp_path/'recipes')
    packages = load_packages(tmp_path/'recipes')
    sequence = order(packages, plan['targets'])
    for name in ('bzip2-final','flex-final','bc-final'):
        assert sequence.index(name) < sequence.index('binutils-final')
        assert packages[name].licensing is not None
        assert packages[name].steps['test']
    assert packages['binutils-final'].test_dependencies == ('bzip2-final','bc-final')
