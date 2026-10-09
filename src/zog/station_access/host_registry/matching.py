"""Enrollment hints select a record, never authorize a key. Call under identity.locked."""
import re
from .models import Host


def cloud_identity(report):
    cloud = report.get('cloud', {})
    if not cloud:
        return None
    patterns = {'account_id': r'[0-9]{12}', 'region': r'[a-z]{2}(?:-[a-z]+)+-[0-9]+',
                'instance_id': r'i-(?:[0-9a-f]{8}|[0-9a-f]{17})'}
    if not isinstance(cloud, dict) or set(cloud) != set(patterns) or any(
        not isinstance(cloud[key], str) or not re.fullmatch(pattern, cloud[key])
        for key, pattern in patterns.items()):
        raise ValueError('AWS hints require a complete valid account ID, region and instance ID')
    return dict(cloud)


def summary(host):
    return {'id': str(host.pk), 'label': host.label, 'provider': host.provider,
            'account_id': host.account_id, 'region': host.region, 'instance_id': host.instance_id,
            'archived': host.archived_at is not None}


def resolve(pending):
    result = {'status': 'conflict', 'host': None, 'cloud': None, 'reason': '', 'candidates': []}
    try:
        cloud = cloud_identity(pending.claims)
    except ValueError as error:
        return result | {'reason': str(error)}
    result['cloud'] = cloud
    matches = list(Host.objects.filter(**cloud)) if cloud else []
    result['candidates'] = [summary(host) for host in matches]
    claimed = Host.objects.filter(pk=pending.claimed_host_id).first() if pending.claimed_host_id else None
    if pending.claimed_host_id and not claimed:
        return result | {'reason': 'The claimed registry UUID does not exist. Resolve the migration target.'}
    if len(matches) > 1:
        return result | {'reason': 'Multiple records match the exact AWS identity. Resolve the records before approval.'}
    matched = matches[0] if matches else None
    if claimed and matched and claimed.pk != matched.pk:
        return result | {'reason': 'The claimed registry UUID conflicts with the exact AWS identity match.'}
    selected = claimed or matched
    if selected:
        result['host'] = summary(selected)
        if selected.archived_at:
            return result | {'reason': 'The matching record is archived. Review and explicitly restore it before approval.'}
        if cloud and (selected.provider != 'aws' or any(getattr(selected, key) != value for key, value in cloud.items())):
            return result | {'reason': 'The claimed record has a different provider or AWS identity. Resolve the conflict.'}
        if not cloud and selected.provider == 'aws':
            return result | {'reason': 'An AWS migration must report its complete AWS identity for comparison.'}
        if selected.identities.filter(status='approved').exclude(fingerprint=pending.fingerprint).exists():
            return result | {'reason': 'The selected host already has another approved key. Explicitly resolve or revoke that identity before approving a replacement.'}
        reason = 'Claimed migration UUID selects the existing record.'
        if cloud:
            reason = 'Exact AWS account, region and instance match.'
            if claimed:reason += ' Migration UUID agrees.'
        return result | {'status': 'existing', 'reason': reason}
    return result | {'status': 'new', 'reason': 'No existing AWS identity match; approval will create an AWS record.' if cloud else 'No cloud identity or migration target reported; approval will create a non-cloud record.'}
