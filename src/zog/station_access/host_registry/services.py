import hashlib
import secrets
from django.db import transaction
from .models import Host

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def enroll(*, host_id=None, account_id="", region="", instance_id="", label="", workspace_id=""):
    from .identity import locked
    with locked():
        # Retained only for explicit legacy provisioning; no public-key approval.
        if host_id:
            host = Host.objects.get(pk=host_id)
        elif instance_id:
            host, _ = Host.objects.get_or_create(provider="aws", account_id=account_id, region=region, instance_id=instance_id, defaults={"label":label, "workspace_id":workspace_id})
        else:
            host = Host.objects.create(label=label, workspace_id=workspace_id)
        if host.archived_at:raise ValueError('Restore archived host before legacy provisioning')
        if host.identities.exists():
            raise ValueError('Legacy enrollment cannot modify a public-key host')
        token = secrets.token_urlsafe(32)
        # Enrollment/rotation never replaces an existing user's label.
        Host.objects.filter(pk=host.pk).update(token_digest=digest(token), token_revoked=False)
        host.refresh_from_db()
        return host, token
