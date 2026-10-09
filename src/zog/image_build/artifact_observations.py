"""Non-executing, bounded ELF and shebang inspection of installed regular files."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .errors import ImageBuildError
from .metadata import identity


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def scan(root, entries, owners, *, readelf='readelf'):
    root=Path(root).resolve();tool=shutil.which(readelf)
    tool_id={'name':'readelf','sha256':sha(Path(tool))} if tool else None
    relationships=[];issues=[];elf_count=0;script_count=0
    def add(subject, relation, kind, value, origin):
        item=dict(subject=subject,relation=relation,target={'kind':kind,'value':value},evidence=origin)
        item['id']='sha256:'+identity(item);relationships.append(item)
    for entry in entries:
        if entry['kind']!='file':continue
        path=root/entry['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ImageBuildError('artifact scan escapes generation')
        expected=entry['sha256']
        if sha(path)!=expected:raise ImageBuildError('artifact bytes changed before inspection')
        subject={'kind':'artifact','path':'/'+entry['path'],'digest':'sha256:'+expected,
                 'packages':owners.get(entry['path'],[])}
        with path.open('rb') as stream:head=stream.read(4096)
        if head.startswith(b'\x7fELF'):
            elf_count+=1
            if not tool:
                issues.append({'path':subject['path'],'reason':'readelf-unavailable'});continue
            with tempfile.TemporaryFile() as output:
                try:
                    run=subprocess.run([tool,'--wide','--program-headers','--dynamic',str(path)],
                        stdout=output,stderr=subprocess.DEVNULL,timeout=10,
                        env={**os.environ,'LC_ALL':'C','LANG':'C'})
                    output.seek(0);raw=output.read(1024*1024+1)
                except subprocess.TimeoutExpired:
                    issues.append({'path':subject['path'],'reason':'readelf-timeout'});continue
            if run.returncode or len(raw)>1024*1024:
                issues.append({'path':subject['path'],'reason':'elf-inspection-failed-or-too-large'});continue
            text=raw.decode('utf-8','replace');origin={'kind':'elf-metadata','tool':tool_id}
            for tag,relation in [('NEEDED','needs-library'),('SONAME','provides-soname')]:
                for value in re.findall(r'\('+tag+r'\)[^\n]*?\[([^\]\n]+)\]',text):
                    add(subject,relation,'soname',value,origin)
            for value in re.findall(r'\[Requesting program interpreter: ([^\]\n]+)\]',text):
                add(subject,'elf-interpreter','path',value,origin)
        elif head.startswith(b'#!'):
            script_count+=1
            line=head.split(b'\n',1)[0]
            if len(line)>255 or len(line)==len(head) or b'\0' in line:
                issues.append({'path':subject['path'],'reason':'unsupported-shebang'});continue
            try:parts=line[2:].decode('utf-8').strip().split(None,1)
            except UnicodeDecodeError:
                issues.append({'path':subject['path'],'reason':'non-utf8-shebang'});continue
            if not parts or not parts[0].startswith('/'):
                issues.append({'path':subject['path'],'reason':'non-absolute-shebang'});continue
            add(subject,'script-interpreter','path',parts[0],{'kind':'shebang',
                'argument':parts[1] if len(parts)>1 else None})
            # /usr/bin/env is the interpreter; its argument is not resolved via
            # the inspection host's PATH or treated as a proven Python dependency.
        if sha(path)!=expected:raise ImageBuildError('artifact bytes changed during inspection')
    return dict(relationships=sorted(relationships,key=lambda r:r['id']),issues=issues,
        coverage={'elf_files':elf_count,'script_files':script_count,'readelf':tool_id,
                  'symlinks':'not-followed','resolution':'interfaces-only',
                  'unsupported':['dlopen','ABI-compatibility','service-dependencies','env-PATH-resolution']})
