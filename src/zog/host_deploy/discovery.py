"""Install signed beacon packages without exporting host identity or credentials."""
import hashlib
import json
import shlex
from urllib.parse import urlsplit
from pathlib import Path
from .provision import configuration, Cloud
from .runner import Host
from .workspace import locked, save

def owned_host(directory):
    workspace, target = configuration(directory)
    observed = Cloud(workspace).owned(target['instance_id'], target['account_id'])
    if observed['State']['Name'] != 'running':
        raise ValueError('Host must already be running; use host-deploy start first')
    host = Host(target)
    host.online()
    return workspace, target, host


def origin(server):
    if not isinstance(server, str) or not server or any(c.isspace() for c in server):
        raise ValueError("server must be an HTTPS origin")
    value=urlsplit(server)
    try: value.port
    except ValueError: raise ValueError("server must be an HTTPS origin") from None
    if value.scheme!='https' or not value.hostname or value.path not in ('','/') or value.query or value.fragment or value.username or value.password:
        raise ValueError('server must be an HTTPS origin')
    return server.rstrip('/')


def installer_settings(configuration_file=None, server=None):
    """Read only explicitly selected, nonsecret settings; no deployment defaults."""
    settings=json.loads(Path(configuration_file).read_text()) if configuration_file else {}
    if not isinstance(settings, dict):
        raise ValueError('Installer configuration must be a JSON object')
    if {'token','password','private_key'} & set(settings):
        raise ValueError('Do not supply secrets in installer configuration')
    if 'server' in settings:
        settings['server']=origin(settings['server'])
    if server is not None:
        server=origin(server)
    return settings, server


def install(directory, registry_directory=None, server=None, source=None, ca_file=None,
            configuration_file=None, migrate=False, system_ca=False,
            server_ready=False, python='python3.12'):
    if not server_ready:
        raise ValueError('Confirm matching command-center pass3 is deployed through migration 0005 with --server-ready')
    if ca_file and system_ca: raise ValueError('Choose custom or system CA trust')
    settings,server=installer_settings(configuration_file,server)
    registry={}
    if registry_directory:
        # Explicit compatibility selection only; never load a bundled live workspace.
        _,registry=configuration(registry_directory)
    from .beacon_payload import payload as build_payload
    payload=build_payload(source);release='/opt/host-discover/releases/'+hashlib.sha256(payload).hexdigest()
    with locked(directory):
        _,target,remote=owned_host(directory)
        path=Path(directory)/'host-discover-install.json'
        receipt=json.loads(path.read_text()) if path.exists() else {}
        cloud={k:target[k] for k in ('account_id','region','instance_id')}
        if receipt:
            if any(k in receipt and receipt[k]!=v for k,v in cloud.items()):
                raise ValueError('Installation receipt target mismatch')
            if any(k not in receipt for k in cloud):
                # Older bearer receipts omitted cloud fields. The owned workspace and
                # remote candidate() still verify the cloud tuple and saved UUID.
                import uuid
                if not migrate or not receipt.get('registry_instance_id'):
                    raise ValueError('Legacy receipt requires explicit migration and a saved command center')
                uuid.UUID(receipt['host_id'])
        previous_registry=receipt.get('registry_instance_id')
        if migrate and previous_registry and registry.get('instance_id')!=previous_registry:
            raise ValueError('Migration requires --registry-workspace for the same command center')
        if previous_registry and registry and registry['instance_id']!=previous_registry:
            raise ValueError('Installation is restricted to the same command center')
        registry_id=registry.get('instance_id') or previous_registry
        ca=Path(ca_file).read_bytes() if ca_file else None
        ca_path=release+'/registry-ca.pem' if ca else None
        request=dict(cloud=cloud,settings=settings,server=server,python=python,migrate=migrate,
                     system_ca=system_ca,ca_path=ca_path,expected_host_id=receipt.get('host_id'))
        # Preflight before uploads or any service change. Never install/downgrade Python implicitly.
        remote.command(shlex.join([python,'-c','import sys,venv; assert sys.version_info >= (3,12), "Python 3.12 required"']))
        # root-owned staging parents must not follow a pre-existing symlink.
        guard="from pathlib import Path; import os; p=Path("+repr(release)+"); "+"[( (_ for _ in ()).throw(ValueError('Unsafe staging path')) if q.is_symlink() or (q.exists() and (q.stat().st_uid!=0 or q.stat().st_mode & 0o022)) else None) for q in [*reversed(p.parents),p]]; p.mkdir(parents=True,exist_ok=True,mode=0o755)"
        remote.command('python3 -c '+shlex.quote(guard))
        remote.upload(payload,release+'/source.zip')
        remote.command('python3 -m zipfile -e '+shlex.quote(release+'/source.zip')+' '+shlex.quote(release))
        if ca:remote.upload(ca,ca_path)
        remote.upload(json.dumps(request).encode(),release+'/request.json')
        save(path,receipt|cloud|{'phase':'staging','release':release,'registry_instance_id':registry_id})
        result=json.loads(remote.command(shlex.join([python,release+'/beacon_install.py','--request',release+'/request.json','--release',release]),seconds=900))
        receipt=receipt|cloud|{'phase':'installed','release':release,'registry_instance_id':registry_id,
               'server':result['server'],'host_id':result.get('host_id'),'fingerprint':result['fingerprint'],
               'enrollment':result['enrollment'],'protocol':'signed-pass3'}
        receipt.pop('configuration_path',None)
        save(path,receipt)
        return result|{'instance_id':target['instance_id']}


def service(directory, action):
    if action not in ('status','start','stop'): raise ValueError('Unknown discovery action')
    with locked(directory):
        _,target,remote=owned_host(directory)
        if action=='start': remote.command('systemctl start host-discover.service')
        if action=='stop': remote.command('systemctl disable --now host-discover.service')
        status=remote.command('systemctl show host-discover.service --property=LoadState,ActiveState,SubState,UnitFileState,Result --no-pager')
        return {'instance_id':target['instance_id'],'service':dict(line.split('=',1) for line in status.splitlines() if '=' in line)}


