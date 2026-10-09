"""Generated original fixture patches apply in declared order with exact hashes."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def test_source_patch_acceptance_fixture(tmp_path,monkeypatch):
    directory=Path(__file__).parents[1]/'acceptance'
    monkeypatch.syspath_prepend(str(directory))
    spec=importlib.util.spec_from_file_location('source_patch_acceptance',directory/'source_patch_provenance.py')
    driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
    driver.prepare_packages(tmp_path)
    for changed in (False,True):
        if changed:driver.configure_sources(tmp_path,changed=True)
        recipe=tmp_path/'package/number-library';sources=driver.literal(recipe/'sources.py')
        from zog.image_build.metadata import load_package
        from zog.image_build.source_provenance import validate
        package=load_package(recipe);validate(package.source_provenance,package.sources)
        workspace=tmp_path/('changed' if changed else 'first');workspace.mkdir();(workspace/'src').mkdir()
        with tarfile.open(tmp_path/'number-library.tar') as tf:tf.extractall(workspace/'src',filter='data')
        for p in package.integration['patches']:
            raw=(tmp_path/p['id']).read_bytes();assert driver.sha(raw)==p['source']['sha256']
            affected=workspace/'src'/p['files'][0]['path'];assert driver.sha(affected.read_bytes())==p['files'][0]['before_sha256']
            subprocess.run(['patch','--batch','--fuzz=0','-p0','-i',str(tmp_path/p['id'])],cwd=workspace,check=True,capture_output=True)
            assert driver.sha(affected.read_bytes())==p['files'][0]['after_sha256']
        assert ('return 42' if changed else 'return 41') in (workspace/'src/number.c').read_text()
        assert (workspace/'src/offset.h').read_text()=='#define ZOG_OFFSET 1\n'
        assert [p['id'] for p in package.integration['patches']]==(['offset-step.patch','number-step.patch'] if changed else ['number-step.patch','offset-step.patch'])
