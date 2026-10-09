"""Commands shared by reviewed Glibc recipes and explicit recovery workers."""
# tests-clean removes markers but not all targets which generate them as side
# effects. Archive first; remove those known targets before rerunning check.
CLEAN_CHECK = r'''set -eu
python3 - <<'CLEAN'
from pathlib import Path
import tarfile,os,time
b=Path('build'); evidence=Path('/image-build/output/usr/share/zog-build-evidence/glibc-final/previous-tests')
evidence.mkdir(parents=True,exist_ok=True)
archive=evidence/('before-clean-'+str(time.time_ns())+'.tar.gz')
standards=['ISO','ISO11','ISO99','POSIX','POSIX2008','UNIX98','XOPEN2K','XOPEN2K8','XPG4','XPG42']
names=['catgets/de/libc.cat','catgets/sample.SJIS.cat','catgets/test1.cat','catgets/test2.cat','timezone/testdata/posixrules']
names += ['conform/symlist-'+prefix+s for prefix in ('','stdlibs-') for s in standards]
files=[p for p in b.rglob('*') if p.is_file() and not p.is_symlink() and (p.name.endswith(('.out','.test-result')) or p.name in ('tests.sum','tests.log'))]
for name in names:
 p=b/name
 assert p.parent.resolve().is_relative_to(b.resolve())
 if p.exists() or p.is_symlink(): files.append(p)
with tarfile.open(archive,'w:gz',dereference=False) as t:
 for p in files:t.add(p,arcname=str(p),recursive=False)
with archive.open('rb') as f:os.fsync(f.fileno())
f=os.open(evidence,os.O_RDONLY|os.O_DIRECTORY);os.fsync(f);os.close(f)
for name in names:(b/name).unlink(missing_ok=True)
CLEAN
make -C build tests-clean
set +e
make -C build -j1 check
result=$?
set -e
if test -f build/tests.sum; then cat build/tests.sum; fi
printf 'Glibc clean suite exit code: %s\n' "$result"
exit "$result"
'''

def cache_command(generator='/usr/sbin/ldconfig', output='/image-build/output/ld.so.cache'):
    """Arguments for execution inside the root whose libraries are being indexed.

    The caller must release that registration before installing the cache into
    a newly recorded root. Never run the generator against the host's libraries.
    """
    return [generator,'-X','-i','-C',output,'/usr/lib']
