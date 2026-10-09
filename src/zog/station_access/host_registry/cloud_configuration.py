"""Saved AWS setup intent; never implicitly selects credentials for existing workers."""
import base64
import json
import os
import re
import uuid
from datetime import timedelta
import boto3
from botocore.config import Config
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from . import vault
from .identity import locked, audit
from .models import CloudCredential
from .setup_configuration import Conflict, check_revision, label
from .provider_checks import CheckBusy

MESSAGES = {
    'never': 'Identity has not been checked.',
    'checking': 'Identity check in progress.',
    'interrupted': 'Check interrupted; retry.',
    'outdated': 'Configuration changed; check again.',
    'passed': 'AWS account identity matched. EC2, SSM and provisioning permissions are not verified.',
    'account_mismatch': 'AWS returned a different account. This credential must not be used for the expected account.',
    'failed': 'Identity check failed. Check credentials, expiry and connectivity.',
}


def aad(row):
    return f'zog-cloud-v1:{row.pk}:{row.account_id}:{row.mode}:{row.region}:{row.revision}'.encode()


def decrypt(row):
    _, keys = vault.keyring()
    raw = base64.b64decode(row.ciphertext, validate=True)
    return json.loads(AESGCM(keys[row.key_id]).decrypt(raw[:12], raw[12:], aad(row)))


def metadata(row):
    now = timezone.now()
    status = row.check_status
    if row.check_revision and row.check_revision != row.revision:
        status = 'outdated'
    elif status == 'checking' and (not row.check_started_at or not 0 <= (now-row.check_started_at).total_seconds() < 60):
        status = 'interrupted'
    expired = bool(row.expires_at and row.expires_at <= now)
    fresh = bool(status == 'passed' and row.enabled and not expired and row.check_finished_at and 0 <= (now-row.check_finished_at).total_seconds() <= 900)
    return dict(id=str(row.pk), provider='aws', label=row.label, account_id=row.account_id,
                mode=row.mode, region=row.region, enabled=row.enabled, expires_at=row.expires_at,
                expired=expired, revision=row.revision, updated_at=row.updated_at,
                check=dict(status=status, message=MESSAGES[status], fresh=fresh, finished_at=row.check_finished_at))


def save(actor, data):
    if set(data)-{'id','revision','label','account_id','mode','region','enabled','secrets','expires_at'}:
        raise ValueError('Unexpected fields')
    account, mode, region = data.get('account_id'), data.get('mode'), data.get('region')
    if not isinstance(account,str) or not re.fullmatch(r'[0-9]{12}',account):
        raise ValueError('Enter the expected 12-digit AWS account ID')
    if mode not in ('default','keys'):raise ValueError('Choose default credentials or saved keys')
    # Use SDK endpoint data, never an administrator-supplied URL.
    if region not in boto3.Session().get_available_regions('sts', partition_name='aws'):
        raise ValueError('Choose a supported commercial AWS region')
    if type(data.get('enabled')) is not bool:raise ValueError('Choose enabled or disabled')
    with locked():
        row = CloudCredential.objects.get(pk=data['id']) if data.get('id') else None
        check_revision(row,data)
        if row and (row.account_id,row.mode)!=(account,mode):
            raise ValueError('Account and credential source are immutable; add another entry')
        values = data.get('secrets')
        expiry = data.get('expires_at')
        if mode == 'default':
            if values is not None or expiry:raise ValueError('Default credentials cannot contain saved keys or expiry')
            values = None
        elif values is None and row:
            values = decrypt(row)
            expiry = row.expires_at
        else:
            if not isinstance(values,dict) or set(values) not in ({'access_key_id','secret_access_key'},{'access_key_id','secret_access_key','session_token'}):
                raise ValueError('Supply access key ID and secret access key')
            if any(not isinstance(v,str) or not 1<=len(v)<=8192 or any(c.isspace() for c in v) for v in values.values()):
                raise ValueError('Invalid AWS credential fields')
            if not re.fullmatch(r'[A-Z0-9]{16,128}',values['access_key_id']):raise ValueError('Invalid AWS access key ID')
            if 'session_token' in values:
                try:expiry=parse_datetime(expiry) if isinstance(expiry,str) else None
                except ValueError:expiry=None
                if not expiry or timezone.is_naive(expiry) or expiry<=timezone.now():
                    raise ValueError('Temporary credentials require a future expiry with timezone')
            elif expiry:raise ValueError('Expiry applies only to session credentials')
            else:expiry=None
        if row is None:
            if CloudCredential.objects.count()>=32:raise ValueError('Maximum 32 cloud accounts')
            row=CloudCredential(account_id=account,mode=mode)
        row.label=label(data.get('label'));row.region=region;row.enabled=data['enabled'];row.expires_at=expiry
        row.revision+=1
        if mode=='keys':
            active,keys=vault.keyring();nonce=os.urandom(12);row.key_id=active
            row.ciphertext=base64.b64encode(nonce+AESGCM(keys[active]).encrypt(nonce,json.dumps(values).encode(),aad(row))).decode()
        row.save()
        audit(actor,'save-cloud-credential',credential_id=str(row.pk),revision=row.revision,enabled=row.enabled)
        return metadata(row)


def caller_account(row):
    values=decrypt(row) if row.mode=='keys' else {}
    arguments={f'aws_{key}':value for key,value in values.items()}
    session=boto3.Session(region_name=row.region,**arguments)
    client=session.client('sts', endpoint_url=f'https://sts.{row.region}.amazonaws.com',
        config=Config(connect_timeout=5,read_timeout=10,retries={'total_max_attempts':1}))
    try:
        result=client.get_caller_identity()
        account=result.get('Account')
        if not isinstance(account,str) or not re.fullmatch(r'[0-9]{12}',account):raise ValueError('Invalid identity')
        return account
    finally:client.close()


def check(actor, identifier, revision):
    now=timezone.now()
    with locked():
        row=CloudCredential.objects.get(pk=identifier);check_revision(row,{'revision':revision})
        if not row.enabled:raise ValueError('Enable this entry before checking')
        if row.expires_at and row.expires_at<=now:raise ValueError('Replace expired temporary credentials')
        if row.check_started_at and (now-row.check_started_at).total_seconds()<60:raise CheckBusy('Wait one minute between checks')
        if CloudCredential.objects.filter(check_status='checking',check_started_at__gt=now-timedelta(seconds=60)).exists():raise CheckBusy('Another cloud check is running')
        attempt=uuid.uuid4();row.check_attempt=attempt;row.check_revision=row.revision
        row.check_started_at=now;row.check_finished_at=None;row.check_status='checking';row.save()
        audit(actor,'start-cloud-check',credential_id=str(row.pk),revision=row.revision)
    try:status='passed' if caller_account(row)==row.account_id else 'account_mismatch'
    except Exception:status='failed'  # Never store or return SDK errors, credentials or caller ARN.
    with locked():
        current=CloudCredential.objects.get(pk=identifier)
        if current.check_attempt!=attempt:raise Conflict('A newer identity check replaced this attempt')
        changed=current.revision!=row.revision
        current.check_status='outdated' if changed else status
        current.check_finished_at=timezone.now();current.save()
        audit(actor,'finish-cloud-check',credential_id=str(row.pk),revision=row.revision,result=current.check_status)
    if changed:raise Conflict('Configuration changed during the check; check the new revision')
    return metadata(current)
