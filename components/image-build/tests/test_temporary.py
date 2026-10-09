from pathlib import Path
import pytest
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages,order
from zog.image_build.errors import ImageBuildError
from zog.image_build.temporary import PROBE

ROOT=Path(__file__).parents[1]/'project'

def test_temporary_graph_dependencies_and_output_boundaries(tmp_path):
    plan=stage_recipes(ROOT/'bootstrap/lfs-temporary.py',ROOT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    sequence=order(packages,plan['targets'])
    assert len(sequence)==16
    assert sequence.index('gcc-temporary-libstdcpp')<sequence.index('ncurses-temporary')<sequence.index('bash-temporary')
    assert all(p.output_trees==('sysroot',) for p in packages.values())
    for package in packages.values():
        assert len(package.sources)==1 and len(package.sources[0]['sha256'])==64
        assert '/tools/bin' in package.environment['PATH']
        assert all('/sysroot/' in '/'+name for name in package.outputs)


def test_runtime_acceptance_does_not_use_distribution_tools():
    assert '/usr/bin/cxx-probe' in PROBE
    assert 'ld-linux-x86-64.so.2 --list' in PROBE
    assert '/tools/' not in PROBE and '/sysroot/' not in PROBE
    assert 'make;' in PROBE and 'patch before' in PROBE
