from pathlib import Path
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages, order


def test_acl_fixture_order_and_runtime_exclusion(tmp_path):
    project = Path(__file__).parents[1] / 'project'
    plan = stage_recipes(project / 'bootstrap/systemd-native.py', project / 'package', tmp_path / 'recipes')
    packages = load_packages(tmp_path / 'recipes')
    sequence = order(packages, plan['targets'])
    assert sequence.index('attr-final') < sequence.index('acl-test-bootstrap')
    assert sequence.index('acl-test-bootstrap') < sequence.index('coreutils-acl-test-tools')
    assert sequence.index('coreutils-acl-test-tools') < sequence.index('acl-final')
    runtime = order(packages, plan['targets'], runtime_only=True)
    assert 'acl-test-bootstrap' not in runtime
    assert 'coreutils-acl-test-tools' not in runtime
    check = packages['acl-final'].steps['test'][0][-1]
    assert 'make -j4 check' in check
    assert 'TESTS=' not in check and 'XFAIL_TESTS=' not in check
    assert 'export LD_LIBRARY_PATH="$PWD/.libs"' in check
    configure = packages['coreutils-acl-test-tools'].steps['configure'][0][-1]
    assert '--enable-acl' in configure and '#define USE_ACL 1' in configure

    assert packages["coreutils-acl-test-tools"].environment["LD_LIBRARY_PATH"] == "/opt/zog/acl-test-bootstrap/lib"
