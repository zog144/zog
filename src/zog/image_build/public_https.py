"""Launch a finite HTTPS acceptance application against a pinned Python/CA root.

The host supplies a frozen DNS answer. This checks target TLS, not target DNS.
No active generation is changed and build-job network isolation stays intact.
"""
import argparse
import fcntl
import json
import platform
import socket
from pathlib import Path

from . import ImageBuild, read_selection
from .configuration import configured_runner
from .filesystem import inventory, write_json
from .generation_provenance import prepare, finish
from .metadata import Package
from .provenance import Provenance
from . import host_labels

HOSTNAME = 'www.python.org'
MOUNTPOINTS = {'dev':0o755, 'proc':0o755, 'sys':0o755, 'root':0o750, 'var/tmp':0o1777}
PROBE = '''import json,socket,ssl
address = ADDRESS
hostname = 'www.python.org'
context = ssl.create_default_context()
assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
with socket.create_connection((address,443),timeout=20) as raw:
 with context.wrap_socket(raw,server_hostname=hostname) as tls:
  tls.settimeout(20)
  tls.sendall(b'HEAD / HTTP/1.1\\r\\nHost: www.python.org\\r\\nConnection: close\\r\\n\\r\\n')
  status=tls.recv(1024).split(b'\\r\\n',1)[0].decode('ascii')
  assert status.startswith(('HTTP/1.1 2','HTTP/1.1 3','HTTP/1.0 2','HTTP/1.0 3')),status
  print(json.dumps({'check':'public-https','status':status,'tls':tls.version(),'peer':address,'cafile':ssl.get_default_verify_paths().cafile}),flush=True)
for label,ctx,name,codes in [('wrong-hostname',context,'wrong.invalid',{62}),('untrusted-ca',ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),hostname,{18,19,20,21})]:
 try:
  with socket.create_connection((address,443),timeout=20) as raw:
   with ctx.wrap_socket(raw,server_hostname=name):
    raise AssertionError('invalid certificate accepted: '+label)
 except ssl.SSLCertVerificationError as error:
  assert error.verify_code in codes,(label,error.verify_code,error.verify_message)
  print(json.dumps({'check':label,'rejected':True,'verify_code':error.verify_code}),flush=True)
print('ZOG_PUBLIC_HTTPS_ACCEPTED; target DNS not tested',flush=True)
'''


def run(project, controller, selection, work, base_components):
    project, controller, selection, work = map(lambda x: Path(x).resolve(),
        (project, controller, selection, work))
    work.mkdir(parents=True, exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = project/'state'
        base = read_selection(selection)
        if not base.manifest.get('public_trust_store_verified'):
            raise ValueError('Accepted public CA generation required')
        p = Provenance.from_configuration(state, base.manifest['inputs']['provenance'])
        builder = ImageBuild(package_dir=work/'unused', state_dir=state,
            runner=configured_runner(controller,state), maximum_generations=32, provenance=p)
        components = json.loads(Path(base_components).read_text())
        if set(components) != set(base.manifest['packages']):
            raise ValueError('Exact base package set required')
        built = {name:dict(base.manifest['packages'][name],root=str(Path(path).resolve()))
                 for name,path in components.items()}
        for name,r in built.items():
            if inventory(r['root']) != r['outputs']:
                raise ValueError('Accepted base output changed: '+name)
            p.verify_output(r['provenance'],name,r)
        intent_path=work/'intent.json'
        if intent_path.exists():
            intent=json.loads(intent_path.read_text())
            address=intent['address']
        else:
            address=socket.getaddrinfo(HOSTNAME,443,socket.AF_INET,socket.SOCK_STREAM)[0][4][0]
        command=PROBE.replace('ADDRESS',repr(address))
        expected=dict(schema=1,base=base.generation,components=components,address=address,
            hostname=HOSTNAME,command=command,application=work.name,uid=21001,
            network='host-shared',mountpoints=MOUNTPOINTS,dns_scope='host-resolved address, target DNS not tested')
        if intent_path.exists() and intent!=expected:
            raise ValueError('Frozen HTTPS application inputs changed')
        write_json(intent_path,expected)
        definitions={name:Package(name,(),(),(),{}, {},(),{}) for name in built}
        attempt=state/'image-build/attempts'/(work.name+'-assembly')
        with builder.locked():
            labels=host_labels.snapshot(built)
            material=p._bytes('host-label-omissions.json',labels)
            inputs=dict(schema=2,kind='image',architecture=platform.machine(),
                assembly_attempt=attempt.name,base=base.generation,application=expected,
                provenance=p.configuration(),host_label_evidence=material,
                composition_policy=host_labels.POLICY)
            fixture=p._bytes('application-mountpoints.json',MOUNTPOINTS)
            prepared=prepare(p,attempt,definitions,list(built),built,inputs,
                composition_materials=[material,fixture],
                composition_actions=['Create the empty application mountpoints with modes declared in application-mountpoints.json before publication.'])
            root=host_labels.compose(attempt,built,list(built),labels,directories=MOUNTPOINTS)
            pointer=finish(p,attempt,prepared,root)
            published=builder._publish(root,inputs,'image',dict(build_record=pointer,
                packages={n:{k:v for k,v in r.items() if k!='root'} for n,r in built.items()},
                purpose='finite-python-https-acceptance',host_boot_ready=False))
        from zog.box_control.images import published_selection
        class ExactImage:
            def ensure(self, project):
                return published_selection(project.path,published.generation)
        control=builder.runner.execute.control
        control.image_provider=ExactImage()
        directory=project/'application'/work.name
        directory.mkdir(exist_ok=True)
        definition='application(name='+repr(work.name)+', programs=(program(name="https-verification", command=("/usr/bin/python3", "-I", "-u", "-c", '+repr(command)+'), user="21001", group="21001", working_directory="/tmp", execution_timeout_seconds=120),))\n'
        path=directory/'application.py'
        if path.exists() and path.read_text()!=definition:
            raise ValueError('HTTPS application definition changed')
        path.write_text(definition)
        request=work/'request.json'
        if not request.exists():
            write_json(request,{'request_id':control.issue_application_request_id()})
        runtime=control.launch_application(work.name,request_id=json.loads(request.read_text())['request_id'])
        result=dict(generation=published.generation,canonical_record=pointer['record'],
            application=work.name,runtime_id=runtime.runtime_id,
            programs=[dict(program=r.program,unit=r.unit_name,invocation_id=r.invocation_id) for r in runtime.programs],
            phase='launched',dns_scope=expected['dns_scope'])
        write_json(work/'result.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','controller','selection','work','base-components'):
        parser.add_argument('--'+name,required=True)
    print(json.dumps(run(**vars(parser.parse_args()))),flush=True)

if __name__=='__main__':main()
