# Generated manually for station-access pass 1 revision 2.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="ApplicationOwnership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("application_name", models.CharField(max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="owned_zog_applications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("application_name",)},
        ),
        migrations.CreateModel(
            name="RuntimePresentation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("runtime_id", models.CharField(max_length=255, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="VncWorkspace",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("application_name", models.CharField(max_length=255)),
                ("desired_running", models.BooleanField(default=True)),
                ("launch_request_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("runtime_id", models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                ("instance_id", models.CharField(blank=True, max_length=255, null=True)),
                ("vnc_host", models.CharField(blank=True, max_length=255, null=True)),
                ("vnc_port", models.PositiveIntegerField(blank=True, null=True)),
                ("endpoint_revision", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="vnc_workspaces", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddConstraint(
            model_name="vncworkspace",
            constraint=models.UniqueConstraint(fields=("owner", "name"), name="unique_workspace_name_per_owner"),
        ),
        migrations.CreateModel(
            name="VncAccessGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_digest", models.CharField(db_index=True, max_length=64, unique=True)),
                ("runtime_id", models.CharField(db_index=True, max_length=255)),
                ("endpoint_revision", models.PositiveIntegerField()),
                ("target_host", models.CharField(max_length=255)),
                ("target_port", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="vnc_access_grants", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="access_grants", to="station_access.vncworkspace")),
            ],
        ),
        migrations.AddIndex(
            model_name="vncaccessgrant",
            index=models.Index(fields=["runtime_id", "expires_at"], name="station_acc_runtime_3f40fd_idx"),
        ),
    ]
