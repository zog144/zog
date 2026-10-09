"""SSM transfers with content-bound durable partial files."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex


def digest(data): return hashlib.sha256(data).hexdigest()
def command(host, code): return host.command('python3 -c '+shlex.quote(code))


def upload(host, data, destination):
    expected=digest(data); temporary=destination+'.upload-'+expected
    code=f'''import os,hashlib,json
p={temporary!r}; final={destination!r}
def info(p):
 return [os.path.getsize(p),hashlib.sha256(open(p,'rb').read()).hexdigest()] if os.path.exists(p) else [0,None]
print(json.dumps([info(final),info(p)]))'''
    final, partial=json.loads(command(host,code))
    if final==[len(data),expected]: return
    offset=partial[0]
    if offset>len(data) or partial[1]!=digest(data[:offset]): offset=0
    if offset==0:
        command(host,f"import os; f=open({temporary!r},'wb'); os.chmod({temporary!r},0o600); f.flush(); os.fsync(f.fileno()); f.close()")
    for start in range(offset,len(data),6000):
        encoded=base64.b64encode(data[start:start+6000]).decode()
        command(host,f"import os,base64; f=open({temporary!r},'r+b'); f.seek({start}); f.write(base64.b64decode({encoded!r})); f.flush(); os.fsync(f.fileno()); f.close()")
    command(host,f"import os,hashlib; from pathlib import Path; p={temporary!r}; assert os.path.getsize(p)=={len(data)} and hashlib.sha256(open(p,'rb').read()).hexdigest()=={expected!r}; os.replace(p,{destination!r}); d=os.open(str(Path({destination!r}).parent),os.O_DIRECTORY); os.fsync(d); os.close(d)")


def download(host, source, output):
    size,expected=command(host,f"import os,hashlib; p={source!r}; print(os.path.getsize(p),hashlib.sha256(open(p,'rb').read()).hexdigest())").split()
    size=int(size)
    if size>20*1024*1024: raise ValueError('SSM result exceeds 20 MiB')
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    # Hash in filename binds partial state to immutable content, not only a path.
    partial=output.with_name(output.name+'.download-'+expected)
    with partial.open('r+b' if partial.exists() else 'w+b') as target:
        for offset in range(0,size,12000):
            length=min(12000,size-offset)
            target.seek(offset); previous=target.read(length)
            if len(previous)==length:
                actual=command(host,f"import hashlib; f=open({source!r},'rb'); f.seek({offset}); print(hashlib.sha256(f.read({length})).hexdigest())")
                if digest(previous)==actual: continue
            encoded=command(host,f"import base64; f=open({source!r},'rb'); f.seek({offset}); print(base64.b64encode(f.read({length})).decode())")
            data=base64.b64decode(encoded,validate=True)
            if len(data)!=length: raise ValueError('Truncated remote result')
            target.seek(offset); target.write(data); target.flush(); os.fsync(target.fileno())
        target.truncate(size); target.flush(); os.fsync(target.fileno())
    with partial.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=expected: raise ValueError('Remote result changed or transfer corrupted')
    os.replace(partial,output)
    fd=os.open(output.parent,os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
