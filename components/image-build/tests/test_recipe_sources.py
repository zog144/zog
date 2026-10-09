from dataclasses import replace
from pathlib import Path
import shutil
import pytest
from zog.image_build.metadata import load_package
from zog.image_build.sources import stage
from zog.image_build.errors import ImageBuildError
RECIPE=Path(__file__).resolve().parents[1]/'project/package/gcc/stages/final'
def test_bundled_patch_staging_and_relocation(tmp_path):
    a=load_package(RECIPE)
    shutil.copytree(RECIPE,tmp_path/'final')
    b=load_package(tmp_path/'final')
    assert a.fingerprint==b.fingerprint
    source=b.sources[-1]
    stage(replace(b,sources=(source,)),tmp_path/'staged',tmp_path/'cache')
    assert (tmp_path/'staged'/source['destination']).read_bytes()==(RECIPE/'patches/cpython-gcc15.patch').read_bytes()
    (tmp_path/'final/patches/cpython-gcc15.patch').write_text('changed')
    with pytest.raises(ImageBuildError,match='changed'):
        stage(replace(b,sources=(source,)),tmp_path/'other',tmp_path/'cache')
def test_bundled_patch_escape_rejected(tmp_path):
    b=load_package(RECIPE)
    outside=tmp_path/'outside';outside.write_text('payload')
    root=tmp_path/'recipe';root.mkdir();(root/'escape').symlink_to(outside)
    source=dict(b.sources[-1],url='recipe:escape')
    with pytest.raises(ImageBuildError,match='unsafe'):
        stage(replace(b,sources=(source,),recipe_directory=str(root)),tmp_path/'staged',tmp_path/'cache')
