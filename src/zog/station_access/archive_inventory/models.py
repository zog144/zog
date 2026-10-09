import uuid
from django.db import models


class Observation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey('host_registry.Host', on_delete=models.PROTECT)
    schema_version = models.PositiveIntegerField(default=1)
    role_revision = models.PositiveBigIntegerField()
    observed_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=24)
    serving = models.BooleanField(default=False)
    lease_expires_at = models.PositiveBigIntegerField(null=True)
    preparation = models.JSONField(default=dict)
    summary = models.JSONField(default=dict)
    total = models.PositiveIntegerField()
    complete = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['host', 'complete', '-observed_at'])]


class Entry(models.Model):
    observation = models.ForeignKey(Observation, on_delete=models.CASCADE, related_name='entries')
    position = models.PositiveIntegerField()
    collection = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    metadata = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['observation', 'position'], name='archive_observation_position'),
                       models.UniqueConstraint(fields=['observation', 'collection', 'digest'], name='archive_observation_content')]


class NoticeBundle(models.Model):
    """Immutable authenticated host evidence; not archive download authorization."""
    host = models.ForeignKey('host_registry.Host', on_delete=models.PROTECT)
    collection = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    bundle_digest = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    evidence = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['host', 'collection', 'digest'], name='archive_notice_binding')]
