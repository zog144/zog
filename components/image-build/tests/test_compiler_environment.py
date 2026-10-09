import ast
import subprocess
import sys
from pathlib import Path
import pytest
from zog.image_build.compiler_environment import account_files, install_accounts, GENERATE_LOCALE
from zog.image_build.errors import ImageBuildError
from zog.image_build.final_compiler import PREFLIGHT


def test_accounts_bind_controller_identity_and_reject_conflicts(tmp_path):
    files=account_files({'execution_user_id':21001,'execution_group_id':21002})
    assert 'build-user:x:21001:21002:' in files['etc/passwd']
    assert ':Build user:/tmp:/bin/bash' in files['etc/passwd']
    install_accounts(tmp_path,files);install_accounts(tmp_path,files)
    (tmp_path/'etc/passwd').write_text('existing account database')
    with pytest.raises(ImageBuildError,match='conflicting'):install_accounts(tmp_path,files)
    assert (tmp_path/'etc/passwd').read_text()=='existing account database'


@pytest.mark.parametrize('uid,gid',[(0,1),(1,0),(None,1),(1,65534),(-1,1),(True,1)])
def test_invalid_execution_identity_refused(uid,gid):
    with pytest.raises(ImageBuildError):account_files({'execution_user_id':uid,'execution_group_id':gid})


def test_account_symlink_refused(tmp_path):
    root=tmp_path/'root';root.mkdir();other=tmp_path/'other';other.mkdir()
    (root/'etc').symlink_to(other)
    with pytest.raises(ImageBuildError):install_accounts(root,account_files({'execution_user_id':1,'execution_group_id':1}))
    assert not list(other.iterdir())


def test_locale_and_account_checks_precede_tests():
    assert 'localedef --no-archive -i C -f UTF-8' in GENERATE_LOCALE
    assert "locale.setlocale(locale.LC_ALL, 'C.UTF-8')" in PREFLIGHT
    assert "pwd.getpwuid(os.getuid())" in PREFLIGHT
    assert 'and not probe.stderr' in PREFLIGHT


def test_tcl_feature_selection_removes_adapters_from_build_inputs(tmp_path):
    stage=Path(__file__).parents[1]/'project/package/tcl/stages/final'
    integration=ast.literal_eval((stage/'integration.py').read_text())
    build=ast.literal_eval((stage/'build.py').read_text())
    policy=integration['bundled_packages'];root=tmp_path/'upstream/tcl8.6.18'
    for name in set(policy['included'])|set(policy['excluded']):
        (root/'pkgs'/name).mkdir(parents=True)
        (root/'pkgs'/name/'source.c').write_text(name)
    script=build['configure'][0][-1].split("<<'FEATURES'\n",1)[1].split('\nFEATURES\n',1)[0]
    subprocess.run([sys.executable,'-c',script],cwd=tmp_path,check=True)
    assert {p.name for p in (root/'pkgs').iterdir()}==set(policy['included'])
    for name in policy['excluded']:
        assert (root/'excluded-bundled'/name/'source.c').read_text()==name
    assert 'make test' in build['test'][0][-1]
    assert build['environment']['USER']=='build-user'
