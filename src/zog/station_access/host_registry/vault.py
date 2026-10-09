"""Dedicated AES-GCM credential vault. No secrets in host.report or audit events."""
import base64
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.utils import timezone
from zog.host_identify.storage import read_owned,directory
from .models import StationCredential


def validate(value):
    if value is None:return
    if not isinstance(value,dict) or set(value)!={'username','password'} or value['username']!='station-admin':
        raise ValueError('Invalid station credential')
    if not isinstance(value['password'],str) or not 1<=len(value['password'])<=4096 or '\x00' in value['password']:
        raise ValueError('Invalid station credential')


def keyring():
    path=Path(settings.HOST_VAULT_CONFIGURATION)
    directory(path.parent)
    config=json.loads(read_owned(path,0o600))
    if set(config)!={'active','keys'} or not isinstance(config['keys'],dict) or not 1<=len(config['keys'])<=8:
        raise ValueError('Invalid vault configuration')
    keys={k:base64.b64decode(v,validate=True) for k,v in config['keys'].items()}
    if any(not isinstance(k,str) or not 1<=len(k)<=80 or len(v)!=32 for k,v in keys.items()) or config['active'] not in keys:
        raise ValueError('Invalid vault keyring')
    return config['active'],keys


def aad(host_id,revision):
    return f'zog-station-vault-v1:{host_id}:{revision}'.encode()


def decrypt(record,keys):
    raw=base64.b64decode(record.ciphertext,validate=True)
    data=AESGCM(keys[record.key_id]).decrypt(raw[:12],raw[12:],aad(record.host_id,record.revision))
    value=json.loads(data);validate(value);return value


def store(host,fingerprint,value):
    """Caller holds security gate. Missing field is handled by caller; null clears."""
    validate(value)
    if value is None:
        StationCredential.objects.filter(host=host).delete();return None
    active,keys=keyring();now=timezone.now()
    row=StationCredential.objects.filter(host=host).first()
    if row and decrypt(row,keys)==value and row.key_id==active and row.source_fingerprint==fingerprint:
        row.received_at=now;row.save(update_fields=['received_at']);return row.revision
    revision=row.revision+1 if row else 1
    nonce=os.urandom(12)
    cipher=nonce+AESGCM(keys[active]).encrypt(nonce,json.dumps(value,separators=(',',':')).encode(),aad(host.pk,revision))
    StationCredential.objects.update_or_create(host=host,defaults={'key_id':active,'ciphertext':base64.b64encode(cipher).decode(),
        'revision':revision,'source_fingerprint':fingerprint,'changed_at':now,'received_at':now})
    return revision


def metadata(host):
    row=StationCredential.objects.filter(host=host).first()
    if not row:return {'available':False}
    return {'available':True,'username':'station-admin','revision':row.revision,'changed_at':row.changed_at,'received_at':row.received_at,
            'source_active':host.identities.filter(fingerprint=row.source_fingerprint,status='approved').exists()}
