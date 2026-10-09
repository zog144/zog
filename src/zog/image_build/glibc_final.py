"""Finalize a retained, tested Glibc build without replaying failed commands.

This explicit recovery workflow preserves the original pipeline evidence. It does
not mark the complete toolchain self-hosted or resume later compiler packages.
"""
import argparse
import collections
import fcntl
import json
import logging
import os
import platform
import re
import shutil
import time
from pathlib import Path
from .box_control_adapter import BuildExecutionPending, BuildRegistrationPending
from .configuration import configured_runner
from .engine import ImageBuild, read_selection
from .filesystem import inventory, digest, merge, write_json, sync_tree
from .metadata import identity
from .native import remove_owned
from .stages import recorded_root
from .developer.seed_build import verify

INSTALL = r'''set -eu
export DESTDIR=/image-build/output/final-glibc-package
if test -e "$DESTDIR"; then echo 'Installation staging already exists; inspect before retry'; exit 1; fi
mkdir -p "$DESTDIR/etc"
touch "$DESTDIR/etc/ld.so.conf"
# The upstream installation test assumes installation into the running root.
# Verify the staged installation in a new isolated root instead.
sed '/test-installation/s@$(PERL)@echo not running@' -i upstream/glibc-2.44/Makefile
make -C build -j1 DESTDIR="$DESTDIR" install
sed '/RTLDLIST=/s@/usr@@g' -i "$DESTDIR/usr/bin/ldd"
mkdir -p "$DESTDIR/usr/share/zog-build-evidence/glibc-final"
cp /image-build/output/result-recovery-tests.sum "$DESTDIR/usr/share/zog-build-evidence/glibc-final/tests.sum"
printf 'Final Glibc staged successfully\n'
'''
CACHE = ['/bin/bash','-eu','-c',
 '/usr/sbin/ldconfig -X -i -C /image-build/output/ld.so.cache /usr/lib; '
 '/usr/sbin/ldconfig -p -C /image-build/output/ld.so.cache; test -s /image-build/output/ld.so.cache']
PROBE = r'''set -eu
printf 'Verifying installed final Glibc\n'
test ! -e /tools; test ! -e /sysroot
if touch /usr/forbidden-write 2>/dev/null; then exit 1; fi
/bin/bash --noprofile --norc -c 'printf "Candidate shell works\n"'
printf '%s  /usr/lib/libc.so.6\n%s  /usr/lib/ld-linux-x86-64.so.2\n' LIBC_HASH LOADER_HASH | sha256sum -c -
cat > candidate.c <<'EOF'
#include <gnu/libc-version.h>
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
int main(void) {
 printf("glibc=%s\n",gnu_get_libc_version());
 if(strcmp(gnu_get_libc_version(),"2.44")) return 1;
 FILE *f=fopen("/proc/self/maps","r"); if(!f) return 2;
 char b[4096]; int found=0;
 while(fgets(b,sizeof b,f)) if(strstr(b,"libc.so.6") || strstr(b,"ld-linux")) {
  fputs(b,stdout); if(strstr(b,"/usr/lib/libc.so.6")) found=1;
 }
 fclose(f); if(!found) return 3;
 void *handle=dlopen("libc.so.6",RTLD_NOW|RTLD_LOCAL);
 if(!handle){fputs(dlerror(),stderr);return 4;}
 dlerror();
 const char *(*version)(void)=(const char *(*)(void))dlsym(handle,"gnu_get_libc_version");
 const char *error=dlerror();
 if(error || !version){if(error)fputs(error,stderr);return 5;}
 if(strcmp(version(),"2.44")) return 6;
 if(dlclose(handle)) return 7;
 puts("Native dlopen/dlsym verification passed"); return 0;
}
EOF
cc candidate.c -o /image-build/output/candidate -ldl -Wl,-t > /image-build/output/link.txt 2>&1
/image-build/output/candidate
readelf -l /image-build/output/candidate | tee /image-build/output/interpreter.txt
grep -F '/lib64/ld-linux-x86-64.so.2' /image-build/output/interpreter.txt
readelf -d /image-build/output/candidate > /image-build/output/dynamic.txt
if grep -E '(RPATH|RUNPATH)' /image-build/output/dynamic.txt; then exit 1; fi
/lib64/ld-linux-x86-64.so.2 --list /image-build/output/candidate
/usr/bin/ldd /image-build/output/candidate
python3 -c 'import os,sys,json; assert os.getcwd()=="/image-build/source"; print(json.dumps({"python":sys.version,"execution":"passed"}))'
printf 'Installed Glibc acceptance passed\n'
'''

def accepted_summary(text):
    counts=collections.Counter()
    lines=text.splitlines()
    seen=set()
    for line in lines:
        if not line.strip() or line.strip()=='=== glibc tests ===' or re.fullmatch(r'Running [a-z_.-]+ \.\.\.',line):
            continue
        status,sep,name=line.partition(': ')
        if not sep or not name or status not in {'PASS','XFAIL','UNSUPPORTED'}:
            raise ValueError('Unaccepted test result: '+line)
        if name in seen: raise ValueError('Duplicate test result: '+name)
        seen.add(name)
        counts[status]+=1
    if counts['PASS']<6800: raise ValueError('Incomplete Glibc summary')
    for name in ('stdio-common/tst-fseek','elf/tst-rtld-dash-dash','elf/tst-rtld-does-not-exist'):
        if 'PASS: '+name not in lines: raise ValueError('Missing critical pass: '+name)
    return dict(counts)

def wait_for(work, phase, function):
    while True:
        try:
            return function()
        except BuildRegistrationPending as pending:
            write_json(work/'progress.json', {'phase': phase, 'pending': 'registration',
                'resource_id': pending.resource_id, 'state': pending.state,
                'registration_phase': pending.phase})
            time.sleep(15)
        except BuildExecutionPending as pending:
            write_json(work/'progress.json',{'phase':phase,'job_id':pending.job_id})
            time.sleep(15)

def recover_base_snapshot(directory, destination):
    """Reconstruct exact recorded contents; never edit the published source tree."""
    directory=Path(directory);destination=Path(destination)
    if destination.exists(): return read_selection(destination)
    manifest=json.loads((directory/'manifest.json').read_text())
    expected={r['path']:r for r in manifest['outputs']}
    actual={r['path']:r for r in inventory(directory/'root')}
    differences={n for n in expected.keys()|actual.keys() if expected.get(n)!=actual.get(n)}
    if not differences or not differences.issubset({'dev','proc','root','sys'}):
        raise ValueError('Base differences exceed reviewed empty mount directories')
    for name in differences:
        path=directory/'root'/name
        if name in expected or actual[name]['kind']!='directory' or any(path.iterdir()):
            raise ValueError('Recovery would remove recorded or nonempty content: '+name)
    destination.mkdir(parents=True)
    shutil.copytree(directory/'root',destination/'root',symlinks=True)
    for name in differences:(destination/'root'/name).rmdir()
    shutil.copy2(directory/'manifest.json',destination/'manifest.json')
    # Full standard validation, including generation input identity and all bytes.
    recovered=read_selection(destination)
    sync_tree(destination)
    write_json(destination.parent/'recovery-evidence.json',{'source':str(directory),
        'omitted_empty_directories':{n:actual[n] for n in sorted(differences)},
        'matched_original_manifest':True,'generation':recovered.generation})
    return recovered


def normalize_package(source, root):
    """Normalize the reviewed merged-/usr layout without replacing any file."""
    shutil.copytree(source,root,symlinks=True)
    legacy=root/'sbin'
    if legacy.exists() or legacy.is_symlink():
        if legacy.is_symlink() or not legacy.is_dir():raise ValueError('Unexpected package sbin type')
        target=root/'usr/sbin'
        if target.is_symlink():raise ValueError('Package usr/sbin is a symlink')
        before={r['path']:r for r in inventory(legacy)}
        merge(legacy,target,preserve_existing_directories=True)
        after={r['path']:r for r in inventory(target)}
        if any(after.get(n)!=r for n,r in before.items()):raise ValueError('sbin normalization changed bytes or modes')
        shutil.rmtree(legacy)


def run(project, attempt, base_generation, previous_package, work, recover_empty_mount_directories=False, base_directory=None):
    project=Path(project).resolve();attempt=Path(attempt).resolve();work=Path(work).resolve()
    assert os.getuid()!=0
    work.mkdir(parents=True,exist_ok=True)
    with (work/'operation.lock').open('a+') as lock, (attempt/'operation.lock').open('a+') as prior_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(prior_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (work/'result.json').exists():
            raise RuntimeError('Finalization result exists; inspect it before further action')
        state=project/'state';runner=configured_runner(attempt/'controller.json',state)
        completed=json.loads((attempt/'result-recovery-0.execution.json').read_text())
        checkpoint=json.loads((attempt/'result-recovery-0.controller.json').read_text())
        authoritative=runner.execute.control.refresh_build_job(checkpoint['job_id'])
        assert authoritative['outcome']=='success' and authoritative['exit_code']==0
        assert authoritative['process_cleanup_complete'] and completed['exit_code']==0
        assert authoritative['invocation_id']==completed['invocation_id']
        assert json.loads((attempt/'result-recovery-result.json').read_text())['phase']=='passed'
        summary=attempt/'output/result-recovery-tests.sum'
        counts=accepted_summary(summary.read_text())
        base_directory=Path(base_directory) if base_directory else state/'image-build/generations'/base_generation
        if recover_empty_mount_directories:
            base=recover_base_snapshot(base_directory,work/'base-snapshot'/base_generation)
        else:base=read_selection(base_directory)
        assert base.generation==base_generation
        previous=json.loads(Path(previous_package).read_text())
        prepared=list((state/'image-build/attempts').glob('image-*/packages/glibc-final/prepared.json'))
        assert len(prepared)==1, 'Need unambiguous original build provenance'
        original=json.loads(prepared[0].read_text())
        evidence={'counts':counts,'summary_sha256':digest(summary),'test_job':authoritative['job_id'],
                  'invocation_id':authoritative['invocation_id'],'execution':completed,
                  'original_preparation':original,'original_preparation_path':str(prepared[0]),
                  'base_generation':base.generation,'previous_package_identity':previous['identity']}
        binding={'evidence':evidence,'install_command':INSTALL,'cache_command':CACHE,
                 'probe_template':PROBE,'package_layout':'merged-usr-v1','policy':runner.execute.configuration()}
        if (work/'intent.json').exists(): assert json.loads((work/'intent.json').read_text())==binding
        else:write_json(work/'intent.json',binding)
        write_json(work/'acceptance.json',evidence)
        try:
            write_json(work/'progress.json',{'phase':'install'})
            command=['/bin/bash','-eu','-c',INSTALL]
            write_json(attempt/'final-install-0.view.json',{'schema':1,'attempt_id':attempt.name,
                'pipeline_id':None,'stage_id':'glibc-final-install','package':'glibc','phase':'install',
                'command_index':0,'command':command,'checkpoint':'final-install-0.controller.json'})
            wait_for(work,'install',lambda:runner.run(attempt/'root',attempt/'source',attempt/'output',
                command,{'USER':'build-user','LOGNAME':'build-user'},attempt/'final-install-0.log'))
            runner.execute.release_resources(attempt)
            staged=attempt/'output/final-glibc-package'
            write_json(work/'staged-package-manifest.json',{'outputs':inventory(staged)})
            package=recorded_root(work/'normalized-package',{'staged':inventory(staged),'layout':'merged-usr-v1'},
                                 lambda root:normalize_package(staged,root))
            package_manifest=inventory(package)
            write_json(work/'package-manifest.json',{'outputs':package_manifest,'acceptance':identity(evidence)})
            builder=ImageBuild(package_dir=work,state_dir=state,runner=runner,maximum_generations=16)
            def assemble(root):
                shutil.copytree(base.root,root,symlinks=True)
                remove_owned(root,previous['outputs'])
                merge(package,root,preserve_existing_directories=True)
            write_json(work/'progress.json',{'phase':'compose'})
            candidate=recorded_root(work/'candidate-root',{'base':base.generation,'package':package_manifest},assemble)
            cache_work=state/'image-build/attempts'/(work.name+'-cache')
            wait_for(work,'cache',lambda:verify(builder,cache_work,candidate,[CACHE],identity(binding)))
            cache=cache_work/'output/ld.so.cache'
            def add_cache(root):
                shutil.copytree(candidate,root,symlinks=True)
                target=root/'etc/ld.so.cache'
                assert not target.is_symlink()
                if target.exists():target.unlink()
                shutil.copy2(cache,target);target.chmod(0o644)
            final=recorded_root(work/'verified-root',{'candidate':inventory(candidate),'cache':digest(cache)},add_cache)
            probe=PROBE.replace('LIBC_HASH',digest(package/'usr/lib/libc.so.6')).replace('LOADER_HASH',digest(package/'usr/lib/ld-linux-x86-64.so.2'))
            verify_work=state/'image-build/attempts'/(work.name+'-verify')
            wait_for(work,'verify',lambda:verify(builder,verify_work,final,[['/bin/bash','-eu','-c',probe]],identity(binding)))
            write_json(work/'progress.json',{'phase':'publish'})
            with builder.locked():
                selection=builder._publish(final,{'schema':2,'kind':'native-final-libc','architecture':platform.machine(),'base':base.generation,
                    'package':package_manifest,'acceptance':identity(evidence),'outputs':inventory(final)},
                    'native-final-libc',{'source_built':True,'self_hosted':False,'build_environment_complete':True,
                    'glibc_version':'2.44','test_counts':counts,'verification':json.loads((verify_work/'verification.json').read_text())})
            write_json(work/'result.json',{'phase':'complete','generation':selection.generation,
                'root':str(selection.root),'self_hosted':False,'installed':True,'published':True})
            print('FINAL GLIBC GENERATION',selection.generation,flush=True)
        except Exception as error:
            write_json(work/'result.json',{'phase':'failed','error':str(error),'published':False})
            raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('project','attempt','base-generation','previous-package','work'):p.add_argument('--'+name,required=True)
    p.add_argument('--recover-empty-mount-directories',action='store_true')
    p.add_argument('--base-directory')
    a=p.parse_args();logging.basicConfig(level=logging.INFO)
    run(a.project,a.attempt,a.base_generation,a.previous_package,a.work,a.recover_empty_mount_directories,a.base_directory)
if __name__=='__main__':main()
