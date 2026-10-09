from pathlib import Path
import ast
import tempfile

from zog.image_build.metadata import literal, load_packages, order
from zog.image_build.stages import stage_recipes
from zog.image_build.licensing import expression

PROJECT = Path(__file__).parents[1]/'project'


def test_source_only_python_graph_and_monthly_pins(tmp_path):
    plan = stage_recipes(PROJECT/'bootstrap/python-enrollment.py', PROJECT/'package', tmp_path/'recipes')
    packages = load_packages(tmp_path/'recipes')
    sequence = order(packages, plan['targets'])
    assert len(sequence) == 24
    assert sequence.index('python-flit-core-final') < sequence.index('python-installer-final')
    assert sequence.index('python-setuptools-scm-final') < sequence.index('python-pluggy-final')
    assert sequence.index('python-hatch-vcs-final') < sequence.index('python-urllib3-final')
    assert sequence.index('python-pycparser-final') < sequence.index('python-cffi-final')
    assert sequence.index('python-urllib3-final') < sequence.index('python-requests-final')
    for package in packages.values():
        assert package.integration['patches_complete'] and package.integration['patches'] == []
        assert package.licensing['evidence']
        assert all(path.endswith('.dist-info/METADATA') for path in package.outputs)
        assert all(s['archive'] and '.whl' not in s['url'] for s in package.sources)
        assert package.environment['PIP_NO_INDEX'] == '1'
        # Validate generated shell heredoc Python before dispatch.
        for phase in ('build', 'test'):
            command = package.steps[phase][0][-1]
            marker = 'ZOG_BUILD' if phase == 'build' else 'ZOG_TEST'
            script = command.split("<<'"+marker+"'\n",1)[1].rsplit(marker,1)[0]
            ast.parse(script)


def test_native_signing_is_explicitly_blocked():
    for name in ('cryptography','maturin','http-message-signatures'):
        package = PROJECT/'package'/('python-'+name)
        assert literal(package/'package.py')['recipe_status'] == 'blocked-native-toolchain'
        assert literal(package/'recipe-plan.py')['blockers']
        assert not (package/'stages/final/build.py').exists()


def test_reviewed_cffi_license_identifier():
    expression('MIT-0')
    assert literal(PROJECT/'package/python-cffi/license.py')['expression'] == 'MIT-0'


def test_foreign_windows_launchers_are_explicitly_omitted():
    for name in ('installer', 'setuptools'):
        stage = PROJECT/'package'/('python-'+name)/'stages/final'
        files = literal(stage/'integration.py')['source_omissions']['files']
        assert len(files) == 8 and all(f['path'].endswith('.exe') for f in files)
        assert 'sha256' in literal(stage/'build.py')['prepare'][0][-1]


def test_https_probe_is_bounded_and_keeps_certificate_validation():
    from zog.image_build.public_https import PROBE
    ast.parse(PROBE.replace('ADDRESS', repr('192.0.2.1')))
    assert 'CERT_REQUIRED' in PROBE
    assert 'SSLCertVerificationError' in PROBE
    assert 'timeout=20' in PROBE
    assert 'CERT_NONE' not in PROBE
    assert 'target DNS not tested' in PROBE


def test_wheel_check_ignores_vendored_distribution_metadata(tmp_path, monkeypatch):
    import zipfile
    directory = tmp_path/'dist'
    directory.mkdir()
    with zipfile.ZipFile(directory/'flit_core-3.12.0-py3-none-any.whl','w') as archive:
        archive.writestr('flit_core/vendor/tomli-1.2.3.dist-info/METADATA', 'Name: tomli\nVersion: 1.2.3\n')
        archive.writestr('flit_core-3.12.0.dist-info/METADATA', 'Name: flit_core\nVersion: 3.12.0\n')
    command = literal(PROJECT/'package/python-flit-core/stages/final/build.py')['test'][0][-1]
    script = command.split("<<'ZOG_TEST'\n",1)[1].rsplit('ZOG_TEST',1)[0]
    monkeypatch.chdir(tmp_path)
    exec(compile(script, '<reviewed-wheel-check>', 'exec'), {})
