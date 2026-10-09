"""Locally installed destination lists. Never adopt destinations from heartbeat replies."""
import hashlib
import json
import ssl
from pathlib import Path
from urllib.parse import urlsplit
from zog.host_identify import storage


def origin(value):
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.path not in ('','/') or p.query or p.fragment or any(c.isspace() for c in value):raise ValueError('Invalid registry origin')
    host=p.hostname.encode('idna').decode().lower()
    if ':' in host:host='['+host+']'
    return 'https://'+host+(':'+str(p.port) if p.port and p.port!=443 else '')


def configurations(base,path):
    data=json.loads(storage.read_owned(path,0o600))
    if not isinstance(data,dict) or set(data)!={'version','destinations'} or data['version']!=1:raise ValueError('Invalid destination list')
    rows=data['destinations']
    if not isinstance(rows,list) or not 1<=len(rows)<=16:raise ValueError('Expected 1–16 destinations')
    primary=origin(base['server']);seen=set()
    # Validate the entire list before making any state changes or sending a request.
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'id','label','server','enabled','ca_certificate','revision'}:raise ValueError('Invalid destination')
        server=origin(row['server'])
        if server in seen or type(row['enabled']) is not bool:raise ValueError('Duplicate or invalid destination')
        seen.add(server)
        pem=row['ca_certificate']
        if not isinstance(pem,str) or len(pem)>12000 or 'PRIVATE KEY' in pem:raise ValueError('Invalid CA certificate')
        if pem:
            try:ssl.create_default_context(cadata=pem)
            except (ValueError,ssl.SSLError):raise ValueError('Invalid CA certificate') from None
    if primary not in seen:raise ValueError('Keep the existing primary registry in the list, disabled if necessary')
    root=storage.directory(base['identity_directory'])
    marker=root/'primary-origin.json'
    if marker.exists():
        if json.loads(storage.read_owned(marker,0o600))!={'server':primary}:raise ValueError('Primary registry origin changed; explicit migration required')
    else:storage.atomic(marker,json.dumps({'server':primary}).encode())
    result=[]
    for row in rows:
        server=origin(row['server']);config=dict(base,server=server)
        if server!=primary:
            # No key, UUID, password, role adapter or archive authority is inherited.
            for name in ('host_id','station_login_file','station_login_withdraw','mirror_box_control','archive_mirror','archive_issuer','archive_audience'):
                config.pop(name,None)
            config['observer_only']=True
            other=root/('registry-'+hashlib.sha256(server.encode()).hexdigest())
            other.mkdir(mode=0o700,exist_ok=True);storage.directory(other)
            credentials=other/'credentials';credentials.mkdir(mode=0o750,exist_ok=True);storage.directory(credentials,shared=True)
            config['identity_directory']=str(other);config['credential_directory']=str(credentials)
        ca=Path(config['identity_directory'])/'registry-ca.pem'
        if row['ca_certificate']:
            storage.atomic(ca,row['ca_certificate'].encode());config['ca_file']=str(ca)
        else:config.pop('ca_file',None)
        result.append((row['enabled'],config))
    return result


def withdraw(config):
    storage.clear_credentials(config['credential_directory'])
    if not config.get('observer_only'):
        from .roles import Controller
        Controller(config).tick(withdraw=True)
