"""Host-derived test fixture, following box-control's legacy live-test contract."""
from pathlib import Path
import hashlib,json,os,pwd,re,shutil,subprocess
release=Path('/opt/zog-archive-acceptance-20260927')
project=Path(os.environ.get('ZOG_ACCEPTANCE_PROJECT','/var/lib/zog-archive-acceptance/project'))
root=project/'state/rootfs/generations/archive-python-fixture-v2/root'
assert not root.exists(),'Fixture already exists; do not mutate a prepared root'
root.mkdir(parents=True)
def copy(source):
 source=Path(source)
 target=root/str(source).lstrip('/')
 if source.is_dir():shutil.copytree(source,target,symlinks=True,dirs_exist_ok=True,ignore=shutil.ignore_patterns("site-packages","__pycache__"))
 else:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
for name in ['/usr/lib64/python3.12','/usr/lib/python3.12']:
 if Path(name).exists():copy(name)
for name in ['/usr/bin/python3.12','/bin/sh','/bin/true','/usr/bin/env','/etc/resolv.conf','/etc/nsswitch.conf','/usr/share/zoneinfo']:
 if Path(name).exists():copy(name)
(root/'usr/bin/python3').symlink_to('python3.12')
# Copy each native object's declared shared libraries, keeping their absolute paths.
objects=[root/'usr/bin/python3.12',root/'bin/sh',root/'bin/true']+list(root.glob('usr/lib*/python3.12/**/*.so'))
objects += list((release/'environment').glob('lib*/python3.12/site-packages/**/*.so'))
for obj in objects:
 out=subprocess.run(['ldd',str(obj)],capture_output=True,text=True).stdout
 for lib in re.findall(r'(/[^\s()]+)',out):
  if Path(lib).is_file():copy(lib)
for directory in ['etc','proc','sys','dev','run','tmp','var/lib/station-access','opt/station-python']:(root/directory).mkdir(parents=True,exist_ok=True)
u=pwd.getpwnam('archive-test')
(root/'etc/passwd').write_text(f'root:x:0:0:root:/root:/bin/sh\narchive-test:x:{u.pw_uid}:{u.pw_gid}:Acceptance:/var/lib/station-access:/bin/sh\n')
(root/'etc/group').write_text(f'root:x:0:\narchive-test:x:{u.pw_gid}:\n')
shutil.copytree(release/'wheels',root/'opt/wheels')
shutil.copytree(release/'station-access/frontend/dist',root/'opt/station-frontend')
shutil.copytree(release/'scripts',root/'opt/acceptance')
(root/'.box-control-rootfs.json').write_text(json.dumps({'fingerprint':'archive-python-fixture-v2','provenance':'host-derived acceptance fixture; NOT an image-build generation'}))
for p in root.rglob('*'):
 if not p.is_symlink():p.chmod(p.stat().st_mode & ~0o6000)
# Controller owner may read the fixture but does not own the immutable test inputs.
project.chmod(0o755)
for d in ['application/station-access','package','catalogue']:(project/d).mkdir(parents=True,exist_ok=True)
for p in [project,project/'state',project/'application',project/'application/station-access',project/'package',project/'catalogue']:
 os.chown(p,u.pw_uid,u.pw_gid)
print(json.dumps({'fixture':str(root),'kind':'host-derived-test','uid':u.pw_uid}))
