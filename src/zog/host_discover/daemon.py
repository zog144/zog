"""Small outbound-only HTTPS reporter. No cloud account credentials required."""
import argparse
import json
import logging
import os
from pathlib import Path
import signal
import socket
import ssl
import threading
import urllib.request
from urllib.parse import urlsplit
from urllib.error import HTTPError
import uuid
from . import __version__

class IdentityUnavailableError(RuntimeError):
    """Existing-only identity cannot be loaded; stop without role execution."""


class MigrationBindingError(ValueError):
    """Configured migration target and approved binding disagree; operator repair required."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Redirects are not allowed for authenticated heartbeats')

def validate_configuration(configuration):
    # A proposed/offline contract is not live mount admission. Fail before any
    # implicit legacy initialization, signing, role action or credential write.
    if 'host_bootstrap' in configuration or 'state_contract' in configuration or Path(os.path.abspath(configuration.get('identity_directory','/'))).is_relative_to('/state'):
        raise ValueError('host-install STATE admission is not implemented; legacy bootstrap is forbidden')
    if configuration.get('identity_mode','legacy-bootstrap') not in ('legacy-bootstrap','existing-only'):
        raise ValueError('Unsupported identity mode')
    origin=urlsplit(configuration['server'])
    if origin.scheme!='https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('','/'):
        raise ValueError('server must be an HTTPS origin')
    if configuration.get('host_id'):uuid.UUID(configuration['host_id'])
    if 'token' in configuration:
        raise ValueError('Use staged migration: remove bearer token from signed daemon configuration')
    for name in ('identity_directory','credential_directory'):
        if not Path(configuration[name]).is_absolute():raise ValueError('Absolute state paths required')
    if configuration.get('provider','generic') not in ('generic','aws'):
        raise ValueError('Unsupported provider')
    return configuration

def identity_key(configuration):
    from zog.host_identify import storage
    validate_configuration(configuration)
    loader=storage.load_existing_key if configuration.get('identity_mode')=='existing-only' else storage.load_key
    try:return loader(configuration['identity_directory'])
    except (OSError,ValueError,TypeError):
        if configuration.get('identity_mode')=='existing-only':
            raise IdentityUnavailableError('Existing identity unavailable; recovery required') from None
        raise


def metadata():
    # Link-local metadata must bypass proxies. Tokens live only for this collection.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    base='http://169.254.169.254/latest/'
    request=urllib.request.Request(base+'api/token',method='PUT',headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'})
    with opener.open(request,timeout=2) as response: token=response.read(4096).decode()
    def get(path, optional=False):
        try:
            request=urllib.request.Request(base+path,headers={'X-aws-ec2-metadata-token':token})
            with opener.open(request,timeout=2) as response:return response.read(16384).decode()
        except HTTPError as error:
            if optional and error.code==404:return ''
            raise
    identity=json.loads(get('dynamic/instance-identity/document'))
    return {'cloud':{'account_id':identity['accountId'],'region':identity['region'],'instance_id':identity['instanceId']},
        'public_dns':get('meta-data/public-hostname',True),'public_ip':get('meta-data/public-ipv4',True),'private_ip':get('meta-data/local-ipv4')}

def collect(configuration):
    report={'version':1,'hostname':socket.gethostname(),'daemon_version':__version__,
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    if configuration.get('provider')=='aws':
        observed=metadata()
        if observed['cloud']!=configuration['cloud']:
            raise ValueError('This configuration belongs to a different EC2 instance')
        report.update(observed)
    else:
        report.update({key:configuration[key] for key in ('public_dns','public_ip','private_ip') if key in configuration})
    return report

def announce(configuration, report):
    from zog.host_identify import signatures, storage
    validate_configuration(configuration)
    key=identity_key(configuration)
    root=Path(configuration['identity_directory'])
    storage.purge_expired(configuration['credential_directory'])
    binding=root/'binding.json'
    saved=json.loads(storage.read_owned(binding,0o600)) if binding.exists() else {}
    fingerprint=signatures.fingerprint(key.public_key())
    host_id=saved.get('host_id') if saved.get('fingerprint')==fingerprint else None
    target=str(uuid.UUID(configuration['host_id'])) if configuration.get('host_id') else None
    claimed=target or saved.get('host_id') or ''
    if host_id and target and str(uuid.UUID(host_id)) != target:
        storage.clear_credentials(configuration['credential_directory'])
        from .roles import Controller
        Controller(configuration).tick(withdraw=True)
        raise MigrationBindingError('Saved binding differs from configured migration target; administrator correction required')
    if not host_id:
        storage.clear_credentials(configuration['credential_directory'])
        from .roles import Controller
        Controller(configuration).tick(withdraw=True)
    if host_id:
        path='/api/hosts/'+str(uuid.UUID(host_id))+'/heartbeat/'
        payload=dict(report);subject=host_id
        from .roles import Controller
        controller=Controller(configuration)
        if not configuration.get('observer_only'):payload['mirror_status']=controller.tick(host_id)
        if configuration.get('observer_only'):
            pass
        elif configuration.get('station_login_withdraw') is True:
            payload['station_login']=None
        elif configuration.get('station_login_file'):
            try:
                source=Path(configuration['station_login_file'])
                storage.directory(source.parent)
                login=json.loads(storage.read_owned(source,0o600))
                if set(login)!={'username','password'} or login['username']!='station-admin' or not isinstance(login['password'],str) or not 1<=len(login['password'])<=4096 or '\x00' in login['password']:raise ValueError('Invalid login export')
                payload['station_login']=login
            except Exception as error:
                logging.error('Station login export unavailable (%s)',type(error).__name__)
    else:
        path='/api/hosts/enrollment/'
        subject=claimed or 'pending'
        payload={'public_key':signatures.public_text(key.public_key()),'claimed_host_id':claimed,'report':report}
    prepared=signatures.sign(configuration['server'].rstrip('/')+path,json.dumps(payload,separators=(',',':')).encode(),key,subject)
    context=ssl.create_default_context(cafile=configuration.get('ca_file') or None)
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=context))
    request=urllib.request.Request(prepared.url,data=prepared.body,headers=dict(prepared.headers),method='POST')
    try:
        with opener.open(request,timeout=10) as response:
            if response.status not in (200,202):raise ValueError('Unexpected heartbeat response')
            raw=response.read(32769)
            if len(raw)>32768:raise ValueError('Oversize response')
            value=json.loads(raw)
    except HTTPError as error:
        if error.code in (401,403):
            storage.clear_credentials(configuration['credential_directory'])
            from .roles import Controller
            Controller(configuration).tick(withdraw=True)
        raise
    if not host_id:
        if value.get('status')=='approved' and value.get('fingerprint')==signatures.fingerprint(key.public_key()):
            approved=str(uuid.UUID(value['host_id']))
            if claimed and approved != str(uuid.UUID(claimed)):
                storage.clear_credentials(configuration['credential_directory'])
                raise MigrationBindingError('Approved binding differs from enrollment target; administrator correction required')
            storage.atomic(binding,json.dumps({'host_id':approved,'fingerprint':fingerprint}).encode())
        elif value.get('status')!='pending':raise ValueError('Unexpected enrollment response')
        # Pending enrollment never retains archive credentials, including reused directories.
        storage.clear_credentials(configuration['credential_directory'])
        return
    if configuration.get('observer_only'):
        if value.get('version')!=2 or value.get('host_id')!=str(host_id):raise ValueError('Malformed heartbeat response')
        storage.clear_credentials(configuration['credential_directory'])
        return
    from .roles import validate
    if 'mirror_roles' in value:validate(value['mirror_roles'])
    storage.save_response(configuration['credential_directory'],value,expected_host=host_id,
                          expected_mirror=configuration.get('archive_mirror',''),
                          expected_issuer=configuration.get('archive_issuer',''),expected_audience=configuration.get('archive_audience',''))
    if 'mirror_roles' in value:
        controller.tick(host_id,value['mirror_roles'])


def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--configuration')
    mode.add_argument('--managed-beacon',action='store_true',help='Run explicitly provisioned supervised managed enrollment and heartbeats; no commands')
    mode.add_argument('--managed-state',action='store_true',help='Verify the existing identity using fresh protected observations; no transport')
    parser.add_argument('--destinations',help='Owner-only deployment destination list; additional registries are observation-only')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--fingerprint',action='store_true',help='Print public key fingerprint for trusted-channel comparison')
    arguments=parser.parse_args()
    if arguments.managed_beacon:
        if arguments.destinations or arguments.fingerprint:
            parser.error('--managed-beacon rejects legacy options')
        from .beacon import run
        result=run(arguments.once)
        print(json.dumps(result,sort_keys=True))
        raise SystemExit(0 if result['status']=='managed-beacon-stopped' else 2)
    if arguments.managed_state:
        if arguments.destinations or arguments.fingerprint:
            parser.error('--managed-state does not accept legacy destinations or fingerprint options')
        try:
            from .managed import report
            result=report()
        except ImportError:
            result={'identity_action':'block','code':'managed-dependency-unavailable','live_admission':False,'remote_control_enabled':False}
        print(json.dumps(result,sort_keys=True))
        raise SystemExit(0 if result.get('status')=='existing-identity-verified' else 2)  # Diagnostic only; no legacy role tick.
    if arguments.fingerprint:
        from zog.host_identify import storage, signatures
        configuration=validate_configuration(json.loads(Path(arguments.configuration).read_text()))
        if arguments.destinations:
            from .destinations import configurations
            print(json.dumps([{'server':c['server'],'enabled':enabled,'fingerprint':signatures.fingerprint(identity_key(c).public_key())} for enabled,c in configurations(configuration,arguments.destinations)]))
        else:print(signatures.fingerprint(identity_key(configuration).public_key()))
        return
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    stop=threading.Event()
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,lambda *_:stop.set())
    while not stop.is_set():
        failed=False
        try:
            configuration=validate_configuration(json.loads(Path(arguments.configuration).read_text()))
            from .destinations import configurations, withdraw
            targets=configurations(configuration,arguments.destinations) if arguments.destinations else [(True,configuration)]
        except Exception as error:
            logging.error('Beacon configuration unavailable (%s)',type(error).__name__)
            targets=[];failed=True
        for enabled,configuration in targets:
            try:
                if enabled:
                    announce(configuration,collect(configuration))
                    logging.info('Heartbeat accepted')
                else:withdraw(configuration)
            except Exception as error:
                failed=True
                if isinstance(error,IdentityUnavailableError):
                    logging.error('Existing identity unavailable; recovery required')
                    raise SystemExit(1) from None
                logging.error('Heartbeat failed (%s); retry in 60 seconds',type(error).__name__)
            try:
                if enabled and not configuration.get('observer_only'):
                    from .roles import Controller
                    Controller(configuration).tick()
            except Exception as error:
                logging.error('Mirror reconciliation unavailable (%s)',type(error).__name__)
                failed=True
        if arguments.once:
            if failed:raise SystemExit(1)
            return
        stop.wait(60)
