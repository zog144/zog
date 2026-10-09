import uuid
from django.db import models

class Host(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.CharField(max_length=150, blank=True)
    label = models.CharField(max_length=200, blank=True)
    provider = models.CharField(max_length=20, default="generic")
    account_id = models.CharField(max_length=32, blank=True)
    region = models.CharField(max_length=40, blank=True)
    instance_id = models.CharField(max_length=80, blank=True)
    workspace_id = models.CharField(max_length=80, blank=True)
    signed_last_received = models.DateTimeField(null=True, blank=True)
    signed_dns_report = models.JSONField(default=dict)
    signed_dns_fingerprint = models.CharField(max_length=64, blank=True)
    signed_dns_observed_at = models.DateTimeField(null=True, blank=True)
    legacy_until = models.DateTimeField(null=True, blank=True)
    token_digest = models.CharField(max_length=64, blank=True)
    token_revoked = models.BooleanField(default=False)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_received = models.DateTimeField(null=True, blank=True)
    report = models.JSONField(default=dict)
    aws_observation = models.JSONField(default=dict)
    aws_checked_at = models.DateTimeField(null=True, blank=True)
    aws_missing_since = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account_id", "region", "instance_id"], condition=models.Q(provider="aws"), name="unique_aws_host")]
        ordering = ["label", "id"]

class InventoryScan(models.Model):
    scope = models.CharField(max_length=120, unique=True)
    last_attempt = models.DateTimeField(null=True)
    last_success = models.DateTimeField(null=True)
    error = models.CharField(max_length=500, blank=True)
    instance_count = models.PositiveIntegerField(default=0)

class DnsAssignment(models.Model):
    host = models.OneToOneField(Host, primary_key=True, on_delete=models.PROTECT, related_name='dns_assignment')
    name = models.CharField(max_length=253, unique=True)
    owner_id = models.CharField(max_length=256, unique=True, editable=False)
    enabled = models.BooleanField(default=True)
    revision = models.PositiveBigIntegerField(default=1)
    desired_action = models.CharField(max_length=20, default='waiting')
    desired_address = models.CharField(max_length=45, blank=True)
    applied_revision = models.PositiveBigIntegerField(null=True)
    status = models.CharField(max_length=30, default='pending')
    record_id = models.CharField(max_length=80, blank=True)
    observed_address = models.CharField(max_length=45, blank=True)
    last_attempt = models.DateTimeField(null=True)
    last_success = models.DateTimeField(null=True)
    last_change = models.DateTimeField(null=True)
    next_attempt = models.DateTimeField(null=True)
    failure_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=60, blank=True)
    error = models.CharField(max_length=1000, blank=True)
    last_action = models.CharField(max_length=30, blank=True)

class SecurityGate(models.Model):
    """Singleton write lock serializes security decisions on SQLite and PostgreSQL."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    revision = models.PositiveBigIntegerField(default=0)

class EnrollmentRequest(models.Model):
    fingerprint = models.CharField(primary_key=True, max_length=64)
    public_key = models.CharField(max_length=44)
    claims = models.JSONField(default=dict)
    claimed_host_id = models.CharField(max_length=36, blank=True)
    status = models.CharField(max_length=16, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

class HostIdentity(models.Model):
    fingerprint = models.CharField(primary_key=True, max_length=64)
    public_key = models.CharField(max_length=44)
    host = models.ForeignKey(Host, on_delete=models.PROTECT, related_name='identities')
    status = models.CharField(max_length=16, default='approved')
    approved_by = models.CharField(max_length=150)
    approved_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['host'], condition=models.Q(status='approved'), name='one_approved_key_per_host')]

class ReplayRecord(models.Model):
    fingerprint = models.CharField(max_length=64)
    nonce = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['fingerprint','nonce'], name='unique_signed_request')]

class AdmissionWindow(models.Model):
    bucket = models.CharField(primary_key=True, max_length=80)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

class ArchivePolicy(models.Model):
    host = models.OneToOneField(Host, primary_key=True, on_delete=models.PROTECT)
    operations = models.JSONField(default=list)
    collections = models.JSONField(default=list)

class SecurityAudit(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=40)
    fingerprint = models.CharField(max_length=64, blank=True)
    host_id_text = models.CharField(max_length=36, blank=True)
    details = models.JSONField(default=dict)

class StationCredential(models.Model):
    host = models.OneToOneField(Host, primary_key=True, on_delete=models.PROTECT)
    key_id = models.CharField(max_length=80)
    ciphertext = models.TextField()
    revision = models.PositiveBigIntegerField(default=1)
    source_fingerprint = models.CharField(max_length=64)
    changed_at = models.DateTimeField()
    received_at = models.DateTimeField()

class MirrorRole(models.Model):
    host = models.OneToOneField(Host, primary_key=True, on_delete=models.PROTECT, related_name='mirror_role')
    selected = models.BooleanField(default=False)
    endpoint = models.CharField(max_length=253, blank=True)
    revision = models.PositiveBigIntegerField(default=1)
    changed_at = models.DateTimeField()
    acknowledged_revision = models.PositiveBigIntegerField(default=0)
    reported_state = models.CharField(max_length=20, default='assigned')
    reason = models.CharField(max_length=60, blank=True)
    runtime_id = models.CharField(max_length=120, blank=True)
    observed_at = models.DateTimeField(null=True)
    last_ready_at = models.DateTimeField(null=True)


class ProviderCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=100)
    provider = models.CharField(max_length=20)
    account_id = models.CharField(max_length=32, blank=True)
    key_id = models.CharField(max_length=80)
    ciphertext = models.TextField()
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class DnsProviderSelection(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    credential = models.ForeignKey(ProviderCredential, on_delete=models.PROTECT, null=True)
    revision = models.PositiveIntegerField(default=0)


class BeaconDestination(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=100)
    server = models.CharField(max_length=300, unique=True)
    enabled = models.BooleanField(default=True)
    ca_certificate = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=0)


class ProviderAccessCheck(models.Model):
    credential = models.OneToOneField(ProviderCredential, primary_key=True, on_delete=models.CASCADE, related_name='access_check')
    credential_revision = models.PositiveIntegerField()
    attempt_id = models.UUIDField(default=uuid.uuid4)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=24, default='checking')
    domains = models.JSONField(default=list)
    more_available = models.BooleanField(default=False)
    error_code = models.CharField(max_length=40, blank=True)


class CloudCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=100)
    account_id = models.CharField(max_length=12)
    mode = models.CharField(max_length=16)
    region = models.CharField(max_length=40, default='us-east-1')
    enabled = models.BooleanField(default=True)
    key_id = models.CharField(max_length=80, blank=True)
    ciphertext = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    check_revision = models.PositiveIntegerField(default=0)
    check_attempt = models.UUIDField(null=True)
    check_started_at = models.DateTimeField(null=True)
    check_finished_at = models.DateTimeField(null=True)
    check_status = models.CharField(max_length=24, default='never')


class DeploymentJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey(Host, on_delete=models.PROTECT, related_name='deployment_jobs')
    operation = models.CharField(max_length=16)
    state = models.CharField(max_length=16, default='queued')
    actor = models.CharField(max_length=150)
    request = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    message = models.CharField(max_length=300, blank=True)
    command_id = models.CharField(max_length=80, blank=True)
    command_ids = models.JSONField(default=list)
    checking_outcome = models.BooleanField(default=False)
    attempt_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True)


class ManagedAdmission(models.Model):
    """Independent history; never recreated from a host's claimed checkpoint."""
    host = models.OneToOneField(Host, on_delete=models.PROTECT, primary_key=True)
    fingerprint = models.CharField(max_length=64)
    installation_id = models.UUIDField()
    state_volume_id = models.UUIDField()
    authority_id = models.UUIDField()
    registry_id = models.CharField(max_length=64)
    epoch = models.PositiveBigIntegerField(default=0)
    checkpoint = models.UUIDField()
    request = models.JSONField()
    claims = models.JSONField()


class DnsDestination(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    selection = models.JSONField()
    ledger_path = models.CharField(max_length=500)
    enabled = models.BooleanField(default=False)

class AdditionalDnsAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey('DnsDestination', on_delete=models.PROTECT, related_name='assignments')
    phase = models.CharField(max_length=20, default='ready')
    host = models.ForeignKey(Host, on_delete=models.PROTECT, related_name='additional_dns_assignments')
    name = models.CharField(max_length=253, unique=True)
    owner_id = models.CharField(max_length=256, editable=False)
    enabled = models.BooleanField(default=True)
    revision = models.PositiveBigIntegerField(default=1)
    desired_action = models.CharField(max_length=20, default='waiting')
    desired_address = models.CharField(max_length=45, blank=True)
    applied_revision = models.PositiveBigIntegerField(null=True)
    status = models.CharField(max_length=30, default='pending')
    record_id = models.CharField(max_length=80, blank=True)
    observed_address = models.CharField(max_length=45, blank=True)
    last_attempt = models.DateTimeField(null=True)
    last_success = models.DateTimeField(null=True)
    last_change = models.DateTimeField(null=True)
    next_attempt = models.DateTimeField(null=True)
    failure_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=60, blank=True)
    error = models.CharField(max_length=1000, blank=True)
    last_action = models.CharField(max_length=30, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['host','binding'], name='unique_additional_dns_host_binding')]
