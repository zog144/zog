from pathlib import Path
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages, order
PROJECT = Path(__file__).parents[1] / 'project'


def test_host_boot_plan_materializes_pinned_licensed_packages(tmp_path):
    plan = stage_recipes(PROJECT/'bootstrap/host-boot-packages.py', PROJECT/'package', tmp_path/'recipes')
    packages = load_packages(tmp_path/'recipes')
    assert set(order(packages, plan['targets'])) == {
        'util-linux-nologin', 'dbus-final', 'iproute2-final', 'libseccomp-final', 'e2fsprogs-final'}
    assert 'systemd-final' not in packages
    for package in packages.values():
        assert package.licensing['evidence']
        assert package.steps['test']
    assert packages['util-linux-nologin'].outputs == ('usr/sbin/nologin',)
