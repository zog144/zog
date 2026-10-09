"""Validate the frozen systemd build plan and offline acceptance boundary."""
import ast
from pathlib import Path
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages, order

PROJECT = Path(__file__).parents[1] / 'project'


def test_systemd_stage_and_required_features(tmp_path):
    plan = stage_recipes(PROJECT/'bootstrap/systemd-core.py', PROJECT/'package', tmp_path/'recipes')
    packages = load_packages(tmp_path/'recipes')
    assert order(packages, plan['targets']) == ('systemd-test-environment', 'tzdata-final', 'systemd-final')
    package = packages['systemd-final']
    command = package.steps['configure'][0][-1]
    for option in ('--wrap-mode=nodownload', '--auto-features=disabled', '-Dtests=true',
                   '-Dnetworkd=true', '-Dresolve=true', '-Dtimesyncd=true',
                   '-Dlibmount=enabled', '-Dkmod=enabled', '-Dacl=enabled',
                   '-Dlibcrypt=enabled', '-Dpcre2=enabled', '-Dopenssl=enabled'):
        assert option in command
    test = package.steps['test'][0][-1]
    assert 'meson test' in test and '--no-rebuild' in test and '--print-errorlogs' in test
    assert '--exclude' not in test and '|| true' not in test
    install = package.steps['install'][0][-1]
    assert 'DESTDIR="$DESTDIR" SYSTEMD_OFFLINE=1 meson install' in install
    assert 'systemctl' not in install and 'machine-id-setup' not in install


def test_systemd_notice_scope_and_exact_source_binding():
    package = PROJECT/'package/systemd'
    license = ast.literal_eval((package/'license.py').read_text())
    source = ast.literal_eval((package/'stages/final/sources.py').read_text())[0]
    assert license['source'] == {key:source[key] for key in ('url','sha256')}
    assert license['status'] == 'declared'
    assert 'GPL-2.0-or-later' in license['expression']
    assert 'LGPL-2.1-or-later' in license['expression']
    names = {e['path'] for e in license['evidence']}
    assert {'systemd-261.2/LICENSE.GPL2', 'systemd-261.2/LICENSE.LGPL2.1',
            'systemd-261.2/LICENSES/README.md'}.issubset(names)
    assert all(e['source_sha256'] == source['sha256'] for e in license['evidence'])
    assert not license['patches']


def test_installed_check_is_offline():
    check = (PROJECT/'bootstrap/systemd-core-check.sh').read_text()
    assert 'pkg-config --exists libsystemd libudev' in check
    assert 'sd_id128_from_string' in check and 'udev_new' in check
    assert 'systemd-analyze verify --man=no' in check
    assert 'ZOG_SYSTEMD_CORE_INSTALLED_PASS' in check
    for forbidden in ('systemctl start', 'systemctl enable', 'systemctl preset',
                      'udevadm trigger', 'machine-id-setup', 'reboot'):
        assert forbidden not in check


def test_static_fixture_is_build_only_and_hash_bound(tmp_path):
    import hashlib
    from zog.image_build.sources import stage
    from zog.image_build.licensing import prepare_readability
    stage_recipes(PROJECT/'bootstrap/systemd-core.py', PROJECT/'package', tmp_path/'recipes')
    packages = load_packages(tmp_path/'recipes')
    fixture = packages['systemd-test-environment']
    assert 'test_fixtures' not in packages['systemd-final'].integration
    assert 'systemd-test-environment' not in order(packages, ['systemd-final'], runtime_only=True)
    stage(fixture, tmp_path/'source', tmp_path/'cache')
    prepare_readability(fixture, tmp_path/'source')
    for source in fixture.sources:
        assert hashlib.sha256((tmp_path/'source'/source['destination']).read_bytes()).hexdigest() == source['sha256']
    assert 'Alex Black' in (tmp_path/'source/inputs/COPYRIGHT').read_text()
    assert not (tmp_path/'source/inputs/machine-id').exists()
