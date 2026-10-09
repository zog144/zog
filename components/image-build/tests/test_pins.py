import ast
from pathlib import Path
import pytest
from zog.image_build.errors import ImageBuildError
from zog.image_build.pins import load, validate
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages
from test_source_build import prepared


def test_missing_pin_blocks_before_job(prepared):
    builder, runner, _, toolchain = prepared
    (builder.package_dir/'commit-pin.py').unlink()
    before = len(runner.calls)
    with pytest.raises(ImageBuildError):
        builder.ensure(['consumer'], toolchain=toolchain)
    assert len(runner.calls) == before


def test_source_drift_blocks_before_job(prepared):
    builder, runner, _, toolchain = prepared
    path = builder.package_dir/'library/sources.py'
    source = ast.literal_eval(path.read_text())
    source[0]['sha256'] = '0'*64
    path.write_text(repr(source))
    before = len(runner.calls)
    with pytest.raises(ImageBuildError, match='monthly pin'):
        builder.ensure(['consumer'], toolchain=toolchain)
    assert len(runner.calls) == before


def test_monthly_set_covers_catalogue_and_stage_snapshot(tmp_path):
    project = Path(__file__).resolve().parents[1]/'project'
    pins = load(project/'pins/2026-10-01/commit-pin.py')
    assert set(pins['packages']) == {p.name for p in (project/'package').iterdir()}
    stage_recipes(project/'bootstrap/lfs-final-gcc.py', project/'package', tmp_path/'recipes')
    selected = validate(tmp_path/'recipes', load_packages(tmp_path/'recipes'))
    assert selected['date'] == '2026-10-01'
    assert 'gcc-15.3.0' in selected['packages']['gcc-final']['sources'][0]['url']
    with pytest.raises(ImageBuildError):
        stage_recipes(project/'bootstrap/lfs-final-gcc.py', project/'package', tmp_path/'other', pin_date='../escape')


def test_non_first_day_rejected(tmp_path):
    p = tmp_path/'commit-pin.py'
    p.write_text(repr({'schema':1,'date':'2026-10-02','packages':{}}))
    with pytest.raises(ImageBuildError):
        load(p)
