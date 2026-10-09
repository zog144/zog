"""Compose and verify the temporary target userspace using an accepted cross toolchain."""
import fcntl,json,platform,shutil
from pathlib import Path
from .engine import ImageBuild,read_selection
from .configuration import configured_runner
from .filesystem import ensure_directory,inventory,merge,write_json,discard_staging
from .cleanup import checked_tree
from .stages import recorded_root,stage_recipes
from .developer.seed_build import verify
from .errors import ImageBuildError
from .metadata import names

PROBE=r'''set -eu
printf 'Temporary userspace acceptance\n'
test "$(getconf GNU_LIBC_VERSION)" = 'glibc 2.44'
for tool in bash m4 tic ls diff cmp file find gawk grep gzip make patch sed tar xz; do command -v "$tool"; done
printf 'eval(6*7)\n' | m4 | grep -x 42
printf 'beta\nalpha\n' > original
sort original | sed 's/alpha/ALPHA/' | gawk 'NR==1 {print}' | grep -x ALPHA
cp original copy; cmp original copy
find . -name copy | grep copy
printf 'all:\n\tprintf "make works\\n" > made\n' > Makefile
make; grep -x 'make works' made
printf 'old\n' > before; printf 'new\n' > after
diff -u before after > change.patch || test "$?" = 1
patch before < change.patch; cmp before after
tar -cf saved.tar before original; mkdir restored; tar -xf saved.tar -C restored; cmp before restored/before
gzip -c original > original.gz; gzip -dc original.gz | cmp - original
xz -c original > original.xz; xz -dc original.xz | cmp - original
file /usr/bin/bash | grep ELF
/usr/bin/cxx-probe | grep -x 'C++ target runtime works'
# Every dynamic executable must resolve all its libraries inside this root.
for file in /usr/bin/* /usr/sbin/* /usr/lib/*.so*; do
 test -f "$file" || continue
 case "$(/usr/bin/file -b "$file")" in
  *ELF*'dynamically linked'*|*ELF*'shared object'*) /lib64/ld-linux-x86-64.so.2 --list "$file" ;;
 esac
done
printf 'Temporary userspace acceptance passed\n' | tee /image-build/output/acceptance.txt
'''


def cleanup_assembly(work):
    # Only invoked after durable runtime publication and both verification
    # jobs' release. Completed resume uses generations, never these assemblies.
    for name in ('cross-root','link-root','runtime-root'):
        path=work/name
        checked_tree(path)
        if path.exists():discard_staging(path)
    write_json(work/'assembly-cleanup.json',{'phase':'complete'})


def cross_headers(root):
    """Bridge GCC prefix-relative C++ headers to the separately mounted sysroot."""
    include=Path(root)/'tools/x86_64-zog-linux-gnu/include'
    include.mkdir(parents=True,exist_ok=True)
    (include/'c++').symlink_to('/sysroot/tools/x86_64-zog-linux-gnu/include/c++')


def run(project,catalogue,plan_path,controller,seed_path,cross_path,operation_name='temporary-userspace'):
    names([operation_name])
    project=Path(project).resolve();state=project/'state';work=state/'image-build'/operation_name
    ensure_directory(work)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        plan=stage_recipes(plan_path,catalogue,work/'recipes')
        seed=read_selection(seed_path);cross=read_selection(cross_path)
        if seed.manifest['kind']!='host-bootstrap' or cross.manifest['kind']!='seed-check':
            raise ImageBuildError('temporary userspace requires the recorded distribution seed and cross stage output')
        builder=ImageBuild(package_dir=work/'recipes',state_dir=state,runner=configured_runner(controller,state))
        intent={'plan':plan,'recipes':inventory(work/'recipes'),'seed':seed.generation,'cross':cross.generation,'policy':builder._policy(),'compiler_layout':'separate-sysroot-cxx-v1'}
        path=work/'operation.json';operation=json.loads(path.read_text()) if path.exists() else {'schema':1,'intent':intent,'phase':'build'}
        if operation['intent']!=intent:raise ImageBuildError('temporary userspace inputs changed')
        write_json(path,operation)
        if operation['phase']=='complete':
            read_selection(state/'image-build/generations'/operation['runtime_generation'])
            cleanup_assembly(work)
            return operation
        def prepare(root):
            shutil.copytree(seed.root,root,symlinks=True);merge(cross.root,root,preserve_existing_directories=True)
            cross_headers(root)
        assembled=recorded_root(work/'cross-root',{'seed':seed.generation,'cross':cross.generation,'compiler_layout':'separate-sysroot-cxx-v1'},prepare)
        compiler=builder.import_bootstrap(assembled,{'purpose':'distribution runtime plus source cross compiler','seed':seed.generation,'cross':cross.generation})
        matches=[]
        for p in (state/'image-build/pipelines').glob('*/pipeline.json'):
            r=json.loads(p.read_text())
            if r['operation']=='seed-check' and r['selection']==str(compiler.root.parent) and r['recipes']==intent['recipes'] and r['arguments']['targets']==plan['targets']:matches.append(p)
        if len(matches)>1:raise ImageBuildError('ambiguous temporary userspace pipeline')
        result=builder.resume(matches[0].parent.name) if matches else builder.verify_seed(plan['targets'],host_bootstrap=compiler)
        operation.update(phase='verify',packages_generation=result.generation);write_json(path,operation)
        def link_root(root):
            shutil.copytree(compiler.root,root,symlinks=True);merge(result.root,root,preserve_existing_directories=True)
        linker=recorded_root(work/'link-root',{'compiler':compiler.generation,'packages':result.generation},link_root)
        link=state/'image-build/attempts'/(operation_name+'-cxx-link')
        command=r'''set -eu
printf '#include <iostream>\nint main(){std::cout << "C++ target runtime works\\n";}\n' > probe.cc
/tools/bin/x86_64-zog-linux-gnu-g++ probe.cc -o /image-build/output/cxx-probe -v 2> /image-build/output/link.txt
/tools/bin/x86_64-zog-linux-gnu-readelf -l /image-build/output/cxx-probe
/tools/bin/x86_64-zog-linux-gnu-readelf -d /image-build/output/cxx-probe
'''
        verify(builder,link,linker,[['/bin/bash','-eu','-c',command]],{'compiler':compiler.generation,'packages':result.generation})
        def runtime_root(root):
            shutil.copytree(cross.root/'sysroot',root,symlinks=True)
            merge(result.root/'sysroot',root,preserve_existing_directories=True)
            (root/'bin').symlink_to('usr/bin');(root/'sbin').symlink_to('usr/sbin')
            shutil.copy2(link/'output/cxx-probe',root/'usr/bin/cxx-probe')
            for name in ('tmp','run','image-build/source','image-build/output'):(root/name).mkdir(parents=True,exist_ok=True)
        root=recorded_root(work/'runtime-root',{'cross':cross.generation,'packages':result.generation,'probe':inventory(link/'output')},runtime_root)
        verify(builder,state/'image-build/attempts'/(operation_name+'-verification'),root,[['/bin/bash','-eu','-c',PROBE]],{'cross':cross.generation,'packages':result.generation,'root':inventory(root)})
        with builder.locked():
            published=builder._publish(root,{'schema':2,'kind':'temporary-userspace','cross':cross.generation,'packages':result.generation,'outputs':inventory(root),'architecture':platform.machine()},'temporary-userspace',{'self_hosted':False,'lfs_edition':plan['lfs_edition']})
        operation.update(phase='complete',runtime_generation=published.generation);write_json(path,operation)
        cleanup_assembly(work)
        return operation
