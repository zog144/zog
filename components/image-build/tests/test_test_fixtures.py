import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from zog.image_build.filesystem import inventory,write_json
from zog.image_build.errors import ImageBuildError
from zog.image_build.test_fixtures import prepare


def environment(tmp_path):
 directory=tmp_path/'attempt/packages/glibc';(directory/'root/etc').mkdir(parents=True)
 (directory/'root/etc/passwd').write_text('original')
 (directory/'source').mkdir();(directory/'output').mkdir()
 write_json(directory/'prepared.json',{'root':inventory(directory/'root'),'inputs':{'version':1}})
 spec={'schema':1,'execution_user_id':21001,'execution_group_id':21001,'thread_count_maximum':2048,
       'device_profile':'private-null-permission-test','files':{'etc/passwd':'fixture'},
       'cache_command':['ldconfig'],'cache_artifact':'cache','cache_destination':'etc/ld.so.cache'}
 package=SimpleNamespace(name='glibc',fingerprint='fixed',environment={},integration={'test_fixtures':spec})
 config={k:spec[k] for k in ('execution_user_id','execution_group_id','device_profile')}
 config['resource_limits']={'thread-count-maximum':2048}
 calls=[]
 def run(root,source,output,command,env,log):
  assert (root/'etc/passwd').read_text()=='fixture'
  assert not (root/'etc/ld.so.cache').exists()
  (output/'cache').write_bytes(b'generated from root')
  calls.append(('generate',root))
 builder=SimpleNamespace(_release_resources=lambda path:calls.append(('release',path)),
                         runner=SimpleNamespace(run=run,execute=SimpleNamespace(configuration=lambda:config)))
 return directory,package,builder,config,calls


def test_separate_roots_and_resumption(tmp_path):
 directory,package,builder,config,calls=environment(tmp_path)
 before=inventory(directory/'root')
 root,commands=prepare(builder,package,directory)
 assert inventory(directory/'root')==before
 assert (root/'etc/ld.so.cache').read_bytes()==b'generated from root'
 assert (root/'etc/passwd').read_text()=='fixture'
 assert root.parent==commands
 assert calls[0]==('release',directory)
 assert calls[-1]==('release',directory/'test-fixture-cache')
 assert prepare(builder,package,directory)==(root,commands)
 (root/'etc/passwd').write_text('tampered')
 with pytest.raises(ImageBuildError,match='root changed'):prepare(builder,package,directory)

def test_policy_failure_precedes_release(tmp_path):
 directory,package,builder,config,calls=environment(tmp_path)
 config['device_profile']=None
 with pytest.raises(ImageBuildError,match='policy'):prepare(builder,package,directory)
 assert not calls

def test_fixture_symlink_refused(tmp_path):
 directory,package,builder,config,calls=environment(tmp_path)
 (directory/'root/etc/passwd').unlink();(directory/'root/etc/passwd').symlink_to('/etc/passwd')
 with pytest.raises(ImageBuildError,match='symlink'):prepare(builder,package,directory)


@pytest.mark.parametrize('with_cache',[True,False])
def test_engine_uses_fixture_root_and_retains_evidence_after_cleanup(tmp_path,with_cache):
 from test_source_build import recipe,RecordingRunner
 from zog.image_build.engine import ImageBuild
 from zog.image_build.metadata import load_packages
 from zog.image_build.build_views import read_build_commands
 _,template,_,config,_=environment(tmp_path/'template')
 if not with_cache:
  for key in ('cache_command','cache_artifact','cache_destination'):
   template.integration['test_fixtures'].pop(key)
 recipes=tmp_path/'recipes';recipe(recipes,'glibc')
 (recipes/'glibc/integration.py').write_text(repr(template.integration))
 calls=[];released=[]
 class Runner(RecordingRunner):
  timeout=60
  execute=SimpleNamespace(configuration=lambda:config)
  def run(self,root,source,output,arguments,env,log):
   from zog.image_build.configuration import input_manifest
   assert input_manifest(SimpleNamespace(root=root))
   calls.append((arguments[0],root))
   if arguments[0]=='ldconfig':
    (output/'cache').write_bytes(b'generated');return
   if arguments[0] in ('test','install'):
    assert (root/'etc/passwd').read_text()=='fixture'
    if with_cache:assert (root/'etc/ld.so.cache').read_bytes()==b'generated'
   super().run(root,source,output,arguments,env,log)
 root=tmp_path/'seed';(root/'etc').mkdir(parents=True);(root/'etc/passwd').write_text('original')
 builder=ImageBuild(package_dir=recipes,state_dir=tmp_path/'state',runner=Runner())
 builder._release_resources=lambda path:released.append(path)
 seed=builder.import_bootstrap(root,{})
 attempt=tmp_path/'attempt';attempt.mkdir()
 built=builder._build_set(load_packages(recipes),['glibc'],seed,attempt)
 folder=attempt/'packages/glibc'
 assert [c[0] for c in calls]==(['compile','ldconfig','test','install'] if with_cache else ['compile','test','install'])
 assert calls[0][1]!=calls[-2][1] and calls[-2][1]==calls[-1][1]
 assert (built['glibc']['root']/'usr/share/glibc').read_text()=='glibc'
 assert not (folder/'source').exists()
 assert not (folder/'test-fixture-runtime/root').exists()
 if with_cache:assert (folder/'test-fixture-cache/output/cache').read_bytes()==b'generated'
 views=read_build_commands(attempt)['commands']
 assert {v['phase'] for v in views}==({'build','test-fixture-cache','test','install'} if with_cache else {'build','test','install'})
 assert folder/('test-fixture-runtime' if with_cache else 'test-fixture-cache') in released
 before=len(calls)
 builder._build_set(load_packages(recipes),['glibc'],seed,attempt)
 assert len(calls)==before


def test_files_only_fixture_is_separate_resumable_and_tamper_checked(tmp_path):
 directory,package,builder,config,calls=environment(tmp_path)
 for key in ('cache_command','cache_artifact','cache_destination'):
  package.integration['test_fixtures'].pop(key)
 before=inventory(directory/'root')
 root,commands=prepare(builder,package,directory)
 assert inventory(directory/'root')==before
 assert (root/'etc/passwd').read_text()=='fixture'
 assert not (root/'etc/ld.so.cache').exists()
 assert root.parent==commands
 assert not any(c[0]=='generate' for c in calls)
 assert prepare(builder,package,directory)==(root,commands)
 (root/'etc/passwd').write_text('tampered')
 with pytest.raises(ImageBuildError,match='root changed'):
  prepare(builder,package,directory)


def test_incomplete_fixture_cache_fails_before_resource_release(tmp_path):
 directory,package,builder,config,calls=environment(tmp_path)
 package.integration['test_fixtures'].pop('cache_command')
 with pytest.raises(ImageBuildError,match='incomplete fixture cache'):
  prepare(builder,package,directory)
 assert not calls
