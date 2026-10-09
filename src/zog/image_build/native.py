"""Recorded native temporary compiler transition; no ordinary-build promotion."""
import fcntl,json,logging,os,platform,shutil
from pathlib import Path
from .engine import ImageBuild,read_selection
from .configuration import configured_runner
from .filesystem import inventory,merge,write_json,ensure_directory,discard_staging
from .metadata import names,relative
from .stages import stage_recipes,recorded_root
from .developer.seed_build import verify
from .cleanup import checked_tree
from .errors import ImageBuildError

PROBE=r'''set -eu
test "$(pwd -P)" = /image-build/source
env -u PWD /bin/bash --noprofile --norc -eu -c 'test "$(pwd -P)" = /image-build/source; (cd /usr; test "$(pwd -P)" = /usr); test "$(pwd -P)" = /image-build/source'
test ! -e /tools; test ! -e /sysroot
test -z "$(gcc -print-sysroot)"
test "$(gcc -dumpmachine)" = x86_64-zog-linux-gnu
cat > probe.c <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <gnu/libc-version.h>
int main(void){char *p=getcwd(NULL,0); if(!p)return 1; int e=strcmp(p,"/image-build/source") || strcmp(gnu_get_libc_version(),"2.44"); puts(p);free(p);return e;}
EOF
cc probe.c -o /image-build/output/c-probe
/image-build/output/c-probe
cat > probe.cc <<'EOF'
#include <iostream>
#include <thread>
#include <stdexcept>
int main(){int n=0;std::thread t([&]{n=42;});t.join();try{throw std::runtime_error("exception works");}catch(const std::exception& e){std::cout<<e.what()<<"\n";}if(n!=42)return 1;std::cout<<"Native C++ threads work\n";}
EOF
g++ -pthread probe.cc -o /image-build/output/cxx-probe
/image-build/output/cxx-probe
readelf -l /image-build/output/cxx-probe
readelf -d /image-build/output/cxx-probe > /image-build/output/dynamic.txt
if grep -E '(RPATH|RUNPATH)' /image-build/output/dynamic.txt; then exit 1; fi
gcc -print-search-dirs > /image-build/output/search.txt
/lib64/ld-linux-x86-64.so.2 --list /usr/bin/gcc
/lib64/ld-linux-x86-64.so.2 --list /usr/libexec/gcc/x86_64-zog-linux-gnu/16.2.0/cc1plus
printf 'Native compiler, working-directory, C, C++ exception and thread acceptance passed\n' | tee /image-build/output/acceptance.txt
'''


def remove_owned(root, records, prefix='sysroot/'):
    """Replace only recorded old package files, after matching their actual bytes."""
    root=Path(root);actual={r['path']:r for r in inventory(root)};removals=[];directories=[]
    for item in records:
        if item['path']=='sysroot':continue
        if not item['path'].startswith(prefix):raise ImageBuildError('replacement escapes target tree')
        name=relative(item['path'][len(prefix):]);path=root/name
        if item['kind']=='directory':directories.append(path);continue
        expected=dict(item,path=name)
        if actual.get(name)!=expected:raise ImageBuildError('replacement input changed: '+name)
        for parent in path.relative_to(root).parents:
            if (root/parent).is_symlink():raise ImageBuildError('replacement parent is a symlink')
        removals.append(path)
    for path in removals:
        mode=path.parent.stat().st_mode & 0o777
        path.parent.chmod(mode|0o700)
        try:path.unlink()
        finally:path.parent.chmod(mode)
    for path in sorted(directories,key=lambda p:len(p.parts),reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            mode=path.parent.stat().st_mode & 0o777;path.parent.chmod(mode|0o700)
            try:path.rmdir()
            finally:path.parent.chmod(mode)


def cleanup(work):
    for name in ('compiler-root','native-root','m4-probe-root'):
        path=work/name;checked_tree(path)
        if path.exists():discard_staging(path)
    write_json(work/'assembly-cleanup.json',{'phase':'complete'})


def pipeline(builder,selection,targets,operation):
    matches=[];recipes=inventory(builder.package_dir)
    for path in (builder.state/'image-build/pipelines').glob('*/pipeline.json'):
        saved=json.loads(path.read_text())
        if not saved.get('released') and saved['operation']==operation and saved['selection']==str(selection.root.parent) and saved['recipes']==recipes and saved['arguments']['targets']==targets:matches.append(path)
    if len(matches)>1:raise ImageBuildError('ambiguous native transition pipeline')
    if matches:return builder.resume(matches[0].parent.name)
    if operation=='seed-check':return builder.verify_seed(targets,host_bootstrap=selection)
    return builder.verify_native(targets,toolchain=selection)


def run(project,catalogue,controller,inputs,operation_name='native-toolchain-pass1'):
    names([operation_name]);project=Path(project).resolve();state=project/'state';work=state/'image-build'/operation_name
    ensure_directory(work)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        catalogue=Path(catalogue)
        plan=stage_recipes(catalogue.parent/'bootstrap/lfs-native-temporary.py',catalogue,work/'recipes')
        m4plan=stage_recipes(catalogue.parent/'bootstrap/native-m4.py',catalogue,work/'m4-recipes')
        base=read_selection(inputs['compiler']);runtime=read_selection(inputs['runtime'])
        if base.manifest['kind']!='host-bootstrap' or runtime.manifest['kind']!='temporary-userspace':raise ImageBuildError('native transition requires accepted cross and temporary generations')
        prior=Path(inputs['prior_attempt']);records={}
        for name in ('gcc-temporary-libstdcpp','ncurses-temporary','bash-temporary'):
            folder=prior/'packages'/name;record=json.loads((folder/'result.json').read_text())
            if record['outputs']!=inventory(folder/'output'):raise ImageBuildError('prior package output changed')
            records[name]=record
        builder=ImageBuild(package_dir=work/'recipes',state_dir=state,runner=configured_runner(controller,state),maximum_generations=12)
        intent={'compiler':base.generation,'runtime':runtime.generation,'previous_packages':records,'recipes':inventory(work/'recipes'),'m4_recipes':inventory(work/'m4-recipes'),'policy':builder._policy(),'maximum_generations':12}
        path=work/'operation.json';saved=json.loads(path.read_text()) if path.exists() else {'schema':1,'phase':'build','intent':intent}
        if saved['intent']!=intent:raise ImageBuildError('native transition inputs changed')
        write_json(path,saved)
        if saved['phase']=='complete':read_selection(state/'image-build/generations'/saved['native_generation']);cleanup(work);return saved
        def prepare(root):
            shutil.copytree(base.root,root,symlinks=True)
            for name in ('gcc-temporary-libstdcpp','ncurses-temporary'):merge(prior/'packages'/name/'output',root,preserve_existing_directories=True)
        logging.info('Preparing recorded cross compiler environment')
        compiler_root=recorded_root(work/'compiler-root',{'compiler':base.generation,'packages':{n:records[n]['identity'] for n in records if n!='bash-temporary'}},prepare)
        compiler=builder.import_bootstrap(compiler_root,{'purpose':'native compiler transition','compiler':base.generation,'dependencies':{n:records[n]['identity'] for n in records if n!='bash-temporary'}})
        result=pipeline(builder,compiler,plan['targets'],'seed-check')
        saved.update(phase='native-verification',packages_generation=result.generation);write_json(path,saved)
        def assemble(root):
            shutil.copytree(runtime.root,root,symlinks=True)
            for name in ('bash-temporary','gcc-temporary-libstdcpp'):remove_owned(root,records[name]['outputs'])
            merge(result.root/'sysroot',root,preserve_existing_directories=True)
        root=recorded_root(work/'native-root',{'runtime':runtime.generation,'packages':result.generation},assemble)
        logging.info('Verifying compiler inside source-built root')
        verify(builder,state/'image-build/attempts'/(operation_name+'-compiler-verification'),root,[['/bin/bash','-eu','-c',PROBE]],{'runtime':runtime.generation,'packages':result.generation})
        with builder.locked():
            native=builder._publish(root,{'schema':2,'kind':'native-temporary-toolchain','base':runtime.generation,'packages':result.generation,'outputs':inventory(root),'architecture':platform.machine()},'native-temporary-toolchain',{'self_hosted':False,'source_built':True,'lfs_edition':plan['lfs_edition']})
        saved.update(phase='m4-verification',native_generation=native.generation);write_json(path,saved)
        builder.package_dir=work/'m4-recipes'
        m4=pipeline(builder,native,m4plan['targets'],'native-check')
        def m4_root(root):
            shutil.copytree(native.root,root,symlinks=True);shutil.copytree(m4.root,root/'native-m4',symlinks=True)
        probe=recorded_root(work/'m4-probe-root',{'native':native.generation,'m4':m4.generation},m4_root)
        verify(builder,state/'image-build/attempts'/(operation_name+'-m4-verification'),probe,[['/bin/bash','-eu','-c','test "$(pwd -P)" = /image-build/source; printf "eval(6*7)\\n" | /native-m4/usr/bin/m4 | grep -x 42; printf "Native M4 acceptance passed\\n" | tee /image-build/output/acceptance.txt']],{'native':native.generation,'m4':m4.generation})
        saved.update(phase='complete',m4_generation=m4.generation);write_json(path,saved);cleanup(work);return saved
