"""Administrator setup. Secrets are encrypted, never returned or placed in audit details."""
import base64
import json
import os
import re
import ssl
import uuid
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from . import vault
from .identity import locked, audit
from .models import ProviderCredential, BeaconDestination, DnsProviderSelection

class Conflict(ValueError):
    pass


def origin(value):
    if not isinstance(value,str) or len(value)>300:raise ValueError('Enter an HTTPS registry origin')
    parsed=urlsplit(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment or any(c.isspace() for c in value):
        raise ValueError('Use an HTTPS origin without a path, credentials, query or fragment')
    port=parsed.port
    host=parsed.hostname.encode('idna').decode().lower()
    if ':' in host:host='['+host+']'
    return 'https://'+host+(':'+str(port) if port and port!=443 else '')


def label(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=100:raise ValueError('Enter a label of 1–100 characters')
    return value.strip()


def check_revision(row,data):
    if type(data.get('revision')) is not int or data['revision']!=(row.revision if row else 0):
        raise Conflict('Configuration changed; refresh before saving')


def decrypt_provider(row):
    _,keys=vault.keyring();raw=base64.b64decode(row.ciphertext,validate=True)
    return json.loads(AESGCM(keys[row.key_id]).decrypt(raw[:12],raw[12:],f'zog-provider-v1:{row.pk}:{row.provider}:{row.account_id}:{row.revision}'.encode()))


def provider_metadata(row):
    from .provider_checks import serialize
    return dict(id=str(row.pk),label=row.label,provider=row.provider,account_id=row.account_id,revision=row.revision,
                configured=True,supported=row.provider=='cloudflare',can_check=row.provider in ('cloudflare','porkbun'),updated_at=row.updated_at,access_check=serialize(row))


def save_provider(actor,data):
    if set(data)-{'id','revision','label','provider','account_id','secrets'}:raise ValueError('Unexpected fields')
    with locked():
        row=ProviderCredential.objects.get(pk=data['id']) if data.get('id') else None
        check_revision(row,data)
        provider=data.get('provider');account=data.get('account_id','')
        if provider not in ('cloudflare','porkbun'):raise ValueError('Choose Cloudflare or Porkbun')
        if provider=='cloudflare' and (not isinstance(account,str) or not re.fullmatch('[0-9a-f]{32}',account)):raise ValueError('Cloudflare requires its 32-character account ID')
        if provider=='porkbun':account=''
        if row and (provider,account)!=(row.provider,row.account_id):raise ValueError('Provider and account are immutable; add another credential')
        values=data.get('secrets')
        if values is None and row:values=decrypt_provider(row)
        required={'api_token'} if provider=='cloudflare' else {'api_key','secret_key'}
        if not isinstance(values,dict) or set(values)!=required or any(not isinstance(v,str) or not 1<=len(v)<=4096 or any(c.isspace() for c in v) for v in values.values()):raise ValueError('Supply all required API credentials')
        if row is None:
            if ProviderCredential.objects.count()>=32:raise ValueError('Maximum 32 provider accounts')
            row=ProviderCredential(provider=provider,account_id=account)
        row.label=label(data.get('label'));row.revision+=1
        active,keys=vault.keyring();nonce=os.urandom(12)
        row.key_id=active
        row.ciphertext=base64.b64encode(nonce+AESGCM(keys[active]).encrypt(nonce,json.dumps(values).encode(),f'zog-provider-v1:{row.pk}:{provider}:{account}:{row.revision}'.encode())).decode()
        row.save();audit(actor,'save-provider-credential',credential_id=str(row.pk),revision=row.revision,provider=provider)
        return provider_metadata(row)


def select_dns(actor,data):
    if set(data)!={'credential_id','revision'}:raise ValueError('Unexpected fields')
    with locked():
        selection=DnsProviderSelection.objects.filter(pk=1).first();check_revision(selection,data)
        credential=None
        if data['credential_id']:
            credential=ProviderCredential.objects.get(pk=data['credential_id'])
            if credential.provider!='cloudflare':raise ValueError('Porkbun credential checks are available; the authoritative DNS controller currently supports Cloudflare only')
            path=settings.HOST_DNS_CONFIGURATION
            if not path:raise ValueError('Initialize the authoritative DNS controller before selecting credentials')
            config=json.loads(open(path).read())
            if config['account_id']!=credential.account_id:raise ValueError('Account does not match the existing DNS controller; use its bound account')
            decrypt_provider(credential)
        selection=selection or DnsProviderSelection(pk=1)
        selection.credential=credential;selection.revision+=1;selection.save()
        audit(actor,'select-dns-provider',credential_id=str(credential.pk) if credential else '',revision=selection.revision)


def cloudflare_credentials(config):
    selection=DnsProviderSelection.objects.select_related('credential').filter(pk=1).first()
    if selection and selection.credential:
        row=selection.credential
        if row.provider!='cloudflare' or row.account_id!=config['account_id']:raise ValueError('Provider binding mismatch')
        return row.account_id,decrypt_provider(row)['api_token']
    from zog.network_register.client import credentials
    return credentials(config['token_file'])


def destination_metadata(row):
    return dict(id=str(row.pk),label=row.label,server=row.server,enabled=row.enabled,ca_certificate=row.ca_certificate,revision=row.revision)


def save_destination(actor,data):
    if set(data)-{'id','label','server','enabled','ca_certificate','revision'}:raise ValueError('Unexpected fields')
    server=origin(data.get('server'));pem=data.get('ca_certificate','')
    if type(data.get('enabled')) is not bool:raise ValueError('Choose enabled or disabled')
    if not isinstance(pem,str) or len(pem)>12000:raise ValueError('CA certificate is too large')
    if pem:
        if 'PRIVATE KEY' in pem:raise ValueError('Supply only public CA certificates')
        try:ssl.create_default_context(cadata=pem)
        except (ValueError,ssl.SSLError):raise ValueError('Invalid public CA certificate') from None
    with locked():
        row=BeaconDestination.objects.get(pk=data['id']) if data.get('id') else None;check_revision(row,data)
        if row and server!=row.server:raise ValueError('Registry origins are immutable; disable this destination and add another')
        if BeaconDestination.objects.filter(server=server).exclude(pk=row.pk if row else uuid.uuid4()).exists():raise Conflict('This registry is already in the list')
        if row is None:
            if BeaconDestination.objects.count()>=16:raise ValueError('Maximum 16 destinations')
            row=BeaconDestination(server=server)
        row.label=label(data.get('label'));row.enabled=data['enabled'];row.ca_certificate=pem;row.revision+=1;row.save()
        if len(json.dumps(export_destinations()).encode())>30000:raise ValueError('Combined destination list exceeds 30 KB')
        audit(actor,'save-beacon-destination',destination_id=str(row.pk),revision=row.revision,enabled=row.enabled)
        return destination_metadata(row)


def export_destinations():
    return {'version':1,'destinations':[destination_metadata(row) for row in BeaconDestination.objects.order_by('server')]}
