"""Explicit, administrator-only provider reads. No provider mutation methods."""
import re
import uuid
from datetime import timedelta
from django.utils import timezone
from zog.network_register.client import Client, CloudflareError
from zog.network_register.porkbun import PorkbunClient, PorkbunError
from .identity import locked, audit
from .models import ProviderCredential, ProviderAccessCheck
from .setup_configuration import check_revision, decrypt_provider, Conflict

FRESH_SECONDS = 900
COOLDOWN_SECONDS = 60
MESSAGES = {
    'never': 'No access check recorded.',
    'checking': 'Checking provider domain access.',
    'interrupted': 'The check did not finish. Run it again.',
    'outdated': 'Credentials changed after this check. Run it again.',
    'passed': 'Domain listing succeeded. This does not verify DNS-write permission or visibility of every account domain.',
    'no_domains': 'No domains are visible for this account and token. Account access and DNS-write permission are not confirmed.',
    'provider_unavailable': 'Provider read check failed. Check API credentials, domain access scope and network access. No DNS changes were attempted.',
    'invalid_response': 'Provider returned unexpected domain data. No DNS changes were attempted.',
    'vault_unavailable': 'The saved credential could not be read from the protected vault.',
}


class CheckBusy(Exception):
    pass


def serialize(credential, now=None):
    now = now or timezone.now()
    check = ProviderAccessCheck.objects.filter(credential=credential).first()
    if check is None:
        return {'status': 'never', 'message': MESSAGES['never'], 'fresh': False, 'domains': [], 'more_available': False,
                'started_at': None, 'finished_at': None, 'retry_after_seconds': 0}
    age = (now - check.started_at).total_seconds()
    retry = max(0, COOLDOWN_SECONDS - int(age)) if age >= 0 else COOLDOWN_SECONDS
    status = check.status
    if check.credential_revision != credential.revision:
        status = 'outdated'
    elif status == 'checking' and not 0 <= age < COOLDOWN_SECONDS:
        status = 'interrupted'
    successful = status in ('passed', 'no_domains')
    fresh = bool(successful and check.finished_at and 0 <= (now - check.finished_at).total_seconds() <= FRESH_SECONDS)
    return {'status': status, 'message': MESSAGES.get(check.error_code if status == 'failed' else status, MESSAGES['invalid_response']),
            'fresh': fresh, 'domains': check.domains if successful else [],
            'more_available': check.more_available if successful else False,
            'started_at': check.started_at, 'finished_at': check.finished_at, 'retry_after_seconds': retry}


def list_domains(account, token):
    # One fixed GET to the account-filtered first page. Never follow a supplied URL,
    # use registrar purchase APIs, or enumerate unbounded pages from a web request.
    payload = Client(account, token).request('GET', '/zones', query={'account.id': account, 'page': 1, 'per_page': 50})
    rows = payload.get('result')
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError('Invalid zone list')
    domains = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('account'), dict) or row['account'].get('id') != account:
            raise ValueError('Zone account mismatch')
        identifier, name = row.get('id'), row.get('name')
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{32}', identifier) or identifier in seen:
            raise ValueError('Invalid zone identity')
        if not isinstance(name, str) or len(name) > 253 or '.' not in name or any(not re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in name.split('.')):
            raise ValueError('Invalid domain')
        seen.add(identifier)
        status = row.get('status')
        domains.append({'id': identifier, 'name': name, 'status': status if status in ('active', 'pending', 'initializing', 'moved', 'deleted', 'deactivated') else 'unknown'})
    info = payload.get('result_info', {})
    if not isinstance(info, dict):raise ValueError('Invalid pagination')
    pages = info.get('total_pages', 2 if len(rows) == 50 else 1)
    if type(pages) is not int or pages < 0:raise ValueError('Invalid pagination')
    return sorted(domains, key=lambda row: row['name']), pages > 1


def run(actor, credential_id, revision):
    now = timezone.now()
    with locked():
        credential = ProviderCredential.objects.get(pk=credential_id)
        check_revision(credential, {'revision': revision})
        if credential.provider not in ('cloudflare', 'porkbun'):
            raise ValueError('Unsupported provider')
        check = ProviderAccessCheck.objects.filter(credential=credential).first()
        if check and (now - check.started_at).total_seconds() < COOLDOWN_SECONDS:
            raise CheckBusy('Wait one minute between checks for this account')
        if ProviderAccessCheck.objects.filter(status='checking', started_at__gt=now - timedelta(seconds=COOLDOWN_SECONDS)).exists():
            raise CheckBusy('Another provider check is in progress; retry shortly')
        attempt = uuid.uuid4()
        check, _ = ProviderAccessCheck.objects.update_or_create(credential=credential, defaults={
            'credential_revision': credential.revision, 'attempt_id': attempt, 'started_at': now,
            'finished_at': None, 'status': 'checking', 'domains': [], 'more_available': False, 'error_code': ''})
        audit(actor, 'start-provider-check', credential_id=str(credential.pk), revision=credential.revision)
    # No database transaction or security gate is held while performing network I/O.
    domains, more, error_code = [], False, ''
    try:
        secrets = decrypt_provider(credential)
    except Exception:
        error_code = 'vault_unavailable'
    if not error_code:
        try:
            if credential.provider == 'cloudflare':
                domains, more = list_domains(credential.account_id, secrets['api_token'])
            else:
                page = PorkbunClient(secrets['api_key'], secrets['secret_key']).list_domains()
                domains = page['domains'][:50]
                more = page['more_available'] or len(page['domains']) > 50
        except (CloudflareError, PorkbunError):
            error_code = 'provider_unavailable'
        except Exception:
            error_code = 'invalid_response'
    with locked():
        current = ProviderCredential.objects.get(pk=credential_id)
        check = ProviderAccessCheck.objects.get(credential_id=credential_id)
        if check.attempt_id != attempt:
            raise Conflict('A newer check has replaced this attempt; refresh the account')
        if current.revision != credential.revision:
            check.status = 'outdated'; check.finished_at = timezone.now(); check.save()
            audit(actor, 'finish-provider-check', credential_id=str(current.pk), revision=credential.revision, result='outdated')
            raise_conflict = True
        else:
            check.status = 'failed' if error_code else 'passed' if domains else 'no_domains'
            check.domains = domains; check.more_available = more; check.error_code = error_code
            check.finished_at = timezone.now(); check.save()
            audit(actor, 'finish-provider-check', credential_id=str(current.pk), revision=credential.revision, result=check.status)
            raise_conflict = False
    if raise_conflict:raise Conflict('Credentials changed during the check; refresh and check the new revision')
    return serialize(current)
