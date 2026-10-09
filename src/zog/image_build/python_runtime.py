"""Build the reviewed Python runtime and verify it inside its composed root."""
import argparse
import fcntl
import json
import platform
import shutil
from pathlib import Path

from . import ImageBuild, read_selection
from .configuration import configured_runner
from .developer.seed_build import verify
from .errors import ImageBuildError
from .filesystem import inventory, merge, write_json
from .final_compiler import successful_execution
from .glibc_final import wait_for
from .metadata import identity
from .native import remove_owned
from .stages import recorded_root, stage_recipes

PROBE = r'''
import bz2, ctypes, dbm.gnu, dbm.ndbm, decimal, fcntl, grp, hashlib, http.server
import json, lzma, os, pwd, select, socket, sqlite3, ssl, sys, threading
import urllib.request, uuid, xml.etree.ElementTree, zlib
import compression.zstd, _ssl, _hashlib, _sqlite3, _ctypes, _decimal
import _bz2, _lzma, _zstd, pyexpat, readline, _curses, _curses_panel, _uuid
assert sys.version_info[:2] == (3, 15), sys.version
assert ssl.OPENSSL_VERSION_INFO[0] == 4, ssl.OPENSSL_VERSION
assert hashlib.sha256(b'abc').hexdigest() == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
assert ctypes.CDLL(None).getpid() == os.getpid()
assert pwd.getpwnam('root').pw_uid == 0 and grp.getgrnam('root').gr_gid == 0
assert decimal.Decimal('0.1') + decimal.Decimal('0.2') == decimal.Decimal('0.3')
for codec in (bz2, lzma, zlib, compression.zstd):
    assert codec.decompress(codec.compress(b'zog-runtime')) == b'zog-runtime'
assert xml.etree.ElementTree.fromstring('<root/>').tag == 'root'
for backend in (dbm.gnu, dbm.ndbm):
    with backend.open('/image-build/output/'+backend.__name__, 'c') as db:
        db[b'key'] = b'value'
    with backend.open('/image-build/output/'+backend.__name__, 'r') as db:
        assert db[b'key'] == b'value'
with open('/image-build/output/lock', 'w') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
a, b = socket.socketpair()
a.sendall(b'x'); assert select.select([b], [], [], 2)[0] and b.recv(1) == b'x'
a.close(); b.close()
path = '/image-build/output/python.sqlite3'
with sqlite3.connect(path) as db:
    assert db.execute('pragma journal_mode=WAL').fetchone()[0] == 'wal'
    db.execute('create table sample (value text)')
    db.execute('insert into sample values (?)', ('persisted',))
with sqlite3.connect(path) as db:
    assert db.execute('select value from sample').fetchone()[0] == 'persisted'
    assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
    db.execute('create virtual table words using fts5(value)')
    assert db.execute("select json_extract('{\"v\":42}', '$.v')").fetchone()[0] == 42
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'zog-https-ok')
    def log_message(self, *args): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain('cert.pem', 'key.pem')
server.socket = ctx.wrap_socket(server.socket, server_side=True)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
port = server.server_port
def request(host, context):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    return opener.open(f'https://{host}:{port}/', timeout=10)
try:
    trusted = ssl.create_default_context(cafile='cert.pem')
    assert trusted.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert trusted.security_level >= 2
    with request('localhost', trusted) as response:
        assert response.read() == b'zog-https-ok'
    for host, context in [('127.0.0.1', trusted), ('localhost', ssl.create_default_context())]:
        try:
            request(host, context)
        except urllib.error.URLError as error:
            assert isinstance(error.reason, ssl.SSLCertVerificationError), repr(error)
        else:
            raise AssertionError('invalid certificate was accepted')
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=10)
report = {'python':sys.version,'openssl':ssl.OPENSSL_VERSION,'sqlite':sqlite3.sqlite_version,
          'https_positive':True,'wrong_hostname_rejected':True,'untrusted_ca_rejected':True,
          'public_trust_store_verified':False,'sqlite_persistence':True}
with open('/image-build/output/python-runtime.json', 'w') as stream: json.dump(report, stream, indent=2)
print(json.dumps(report), flush=True)
'''
# Purely local test certificates; public CA distribution is a separate package.
CHECK = "set -eu\nopenssl req -x509 -newkey rsa:2048 -sha256 -noenc -keyout key.pem -out cert.pem -days 1 -subj /CN=localhost -addext subjectAltName=DNS:localhost\npython3 -I - <<'ZOG_PYTHON_PROBE'\n" + PROBE + "\nZOG_PYTHON_PROBE\n"


def ownership(path):
    """Use the preserved original package result, never guess replacement paths."""
    manifest = json.loads(Path(path).read_text())
    record = manifest['packages']['python-native-environment']
    if identity({'inputs':record['inputs'],'outputs':record['outputs']}) != record['identity']:
        raise ImageBuildError('previous Python ownership identity changed')
    files = [r['path'] for r in record['outputs'] if r['kind'] != 'directory']
    if not files or 'usr/bin/python3' not in files or any(not n.startswith('usr/') for n in files):
        raise ImageBuildError('invalid previous Python ownership scope')
    return record


def assemble(destination, base, packages, previous):
    shutil.copytree(base, destination, symlinks=True)
    remove_owned(destination, previous['outputs'], prefix='')
    merge(packages, destination, preserve_existing_directories=True, compose_info=True)


def reviewed_exceptions(package):
    exceptions=package.integration.get('test_exceptions',[])
    for item in exceptions:
        if (item['source_sha256']!=package.sources[0]['sha256'] or
            item['package_version']!=package.licensing['version']):
            raise ImageBuildError('Python test exception requires review for selected source')
    return exceptions


def run(project, catalogue, controller, selection, python_ownership, work, maximum_generations=32):
    project,catalogue,controller,selection,python_ownership,work = map(lambda x:Path(x).resolve(), (project,catalogue,controller,selection,python_ownership,work))
    work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        base=read_selection(selection)
        if base.manifest.get('kind')!='toolchain' or not base.manifest.get('self_hosted') or not base.manifest.get('inputs',{}).get('libraries'):
            raise ImageBuildError('Python requires the accepted OpenSSL/SQLite toolchain generation')
        previous=ownership(python_ownership)
        actual={r['path']:r for r in inventory(base.root)}
        if any(actual.get(r['path'])!=r for r in previous['outputs'] if r['kind']!='directory'):
            raise ImageBuildError('base no longer matches previous Python ownership')
        plan=stage_recipes(catalogue.parent/'bootstrap/python-runtime.py',catalogue,work/'recipes')
        builder=ImageBuild(package_dir=work/'recipes',state_dir=project/'state',runner=configured_runner(controller,project/'state'),maximum_generations=maximum_generations)
        intent={'base':base.generation,'recipes':inventory(work/'recipes'),'previous_python':previous['identity'],'policy':builder._policy(),'maximum_generations':maximum_generations}
        saved=work/'intent.json'
        if saved.exists() and json.loads(saved.read_text())!=intent:raise ImageBuildError('Python runtime inputs changed')
        write_json(saved,intent)
        def build():
            matches=[]
            for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json'):
                r=json.loads(p.read_text())
                if not r.get('released') and r['operation']=='image' and r['selection']==str(base.root.parent) and r['recipes']==intent['recipes'] and r['arguments']['targets']==plan['targets']:matches.append(r['pipeline_id'])
            if len(matches)>1:raise ImageBuildError('ambiguous Python runtime pipeline')
            return builder.resume(matches[0]) if matches else builder.ensure(plan['targets'],toolchain=base)
        from .metadata import load_packages
        exceptions=reviewed_exceptions(load_packages(work/'recipes')['python-final'])
        packages=wait_for(work,'python-runtime',build)
        combined=recorded_root(work/'combined-root',{'intent':intent,'packages':packages.generation},lambda root:assemble(root,base.root,packages.root,previous))
        attempt=builder.state/'image-build/attempts'/work.name
        evidence=wait_for(work,'installed-python',lambda:verify(builder,attempt,combined,[['/bin/bash','-eu','-c',CHECK]],intent))
        execution=successful_execution(attempt)
        with builder.locked():
            accepted=builder._publish(combined,{'schema':2,'kind':'toolchain','stage':2,'architecture':platform.machine(),'base':base.generation,'python':packages.generation,'previous_python':previous['identity'],'test_exceptions':exceptions,'verification':evidence},'toolchain',{'stage':2,'self_hosted':True,'source_built':True,'build_environment_complete':True,'python_runtime_verified':True,'test_exceptions':exceptions,'verification_execution':execution})
        result={'phase':'complete','base':base.generation,'packages':packages.generation,'generation':accepted.generation,'root':str(accepted.root),'public_trust_store_verified':False,'test_exceptions':exceptions}
        write_json(work/'result.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','catalogue','controller','selection','python-ownership','work'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--maximum-generations',type=int,default=32)
    print(json.dumps(run(**vars(parser.parse_args()))),flush=True)

if __name__=='__main__':main()
