import pytest
from zog.image_build.glibc_final import accepted_summary

def summary():
 return '\n'.join(['PASS: stdio-common/tst-fseek','PASS: elf/tst-rtld-dash-dash','PASS: elf/tst-rtld-does-not-exist']+['PASS: test-'+str(i) for i in range(6800)]+['XFAIL: expected','UNSUPPORTED: feature'])
def test_acceptance_keeps_expected_and_unsupported():
 assert accepted_summary(summary())=={'PASS':6803,'XFAIL':1,'UNSUPPORTED':1}
@pytest.mark.parametrize('line',['FAIL: problem','UNRESOLVED: missing','XPASS: unexpected','garbage'])
def test_acceptance_refuses_uncertain_or_failed_results(line):
 with pytest.raises(ValueError):accepted_summary(summary()+'\n'+line)
def test_acceptance_requires_critical_test():
 with pytest.raises(ValueError):accepted_summary(summary().replace('PASS: stdio-common/tst-fseek','UNSUPPORTED: stdio-common/tst-fseek'))

def test_upstream_report_headings():
 assert accepted_summary('\t\t=== glibc tests ===\n\nRunning . ...\nRunning catgets ...\nRunning stdio-common ...\n'+summary())['PASS']==6803

def test_duplicate_results_rejected():
 with pytest.raises(ValueError):accepted_summary(summary()+'\nPASS: stdio-common/tst-fseek')

def test_clean_recipe_removes_side_effect_target_without_following_link(tmp_path):
 import subprocess,sys,tarfile
 from pathlib import Path
 from zog.image_build.glibc_tests import CLEAN_CHECK
 b=tmp_path/'build';t=b/'timezone/testdata';(t/'America').mkdir(parents=True)
 original=t/'America/New_York';original.write_text('timezone')
 (t/'posixrules').symlink_to('America/New_York')
 (b/'tests.sum').write_text('PASS: retained evidence')
 code=CLEAN_CHECK.split("<<'CLEAN'\n",1)[1].split('\nCLEAN',1)[0]
 code=code.replace('/image-build/output',str(tmp_path/'output'))
 result=subprocess.run([sys.executable,'-c',code],cwd=tmp_path,capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 assert original.read_text()=='timezone'
 assert not (t/'posixrules').is_symlink()
 archives=list((tmp_path/'output').rglob('*.tar.gz'));assert len(archives)==1
 with tarfile.open(archives[0]) as archive:
  assert archive.getmember('build/timezone/testdata/posixrules').issym()
  assert archive.extractfile('build/tests.sum').read()==b'PASS: retained evidence'

def test_base_recovery_preserves_source_and_rejects_changed_files(tmp_path):
 import json
 from zog.image_build.glibc_final import recover_base_snapshot
 from zog.image_build.filesystem import inventory
 from zog.image_build.metadata import identity
 inputs={'kind':'native-temporary-toolchain'};generation=identity(inputs)
 source=tmp_path/'source'/generation;root=source/'root';root.mkdir(parents=True)
 (root/'libc').write_text('recorded')
 manifest={'schema':2,'kind':inputs['kind'],'inputs':inputs,'generation':generation,'outputs':inventory(root)}
 (source/'manifest.json').write_text(json.dumps(manifest))
 (root/'dev').mkdir()
 recovered=recover_base_snapshot(source,tmp_path/'snapshot'/generation)
 assert inventory(recovered.root)==manifest['outputs']
 assert (root/'dev').is_dir()
 (root/'libc').write_text('changed')
 with pytest.raises(ValueError):recover_base_snapshot(source,tmp_path/'other'/generation)

def test_base_recovery_refuses_nonempty_added_directory(tmp_path):
 import json
 from zog.image_build.glibc_final import recover_base_snapshot
 source=tmp_path/'source';root=source/'root';root.mkdir(parents=True)
 (source/'manifest.json').write_text(json.dumps({'outputs':[]}))
 (root/'dev').mkdir();(root/'dev/extra').write_text('retain')
 with pytest.raises(ValueError):recover_base_snapshot(source,tmp_path/'snapshot')
 assert (root/'dev/extra').read_text()=='retain'

def test_package_normalization_preserves_file_and_source(tmp_path):
 from zog.image_build.glibc_final import normalize_package
 source=tmp_path/'source';(source/'sbin').mkdir(parents=True)
 (source/'sbin/ldconfig').write_text('compiled bytes');(source/'sbin/ldconfig').chmod(0o755)
 target=tmp_path/'normalized';normalize_package(source,target)
 assert (target/'usr/sbin/ldconfig').read_text()=='compiled bytes'
 assert (target/'usr/sbin/ldconfig').stat().st_mode&0o777==0o755
 assert not (target/'sbin').exists()
 assert (source/'sbin/ldconfig').read_text()=='compiled bytes'

def test_package_normalization_refuses_collision(tmp_path):
 from zog.image_build.glibc_final import normalize_package
 from zog.image_build.errors import ImageBuildError
 source=tmp_path/'source'
 for n in ('sbin','usr/sbin'):
  (source/n).mkdir(parents=True);(source/n/'ldconfig').write_text(n)
 with pytest.raises(ImageBuildError):normalize_package(source,tmp_path/'normalized')
