from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def initialize(apps, schema_editor):
    Workspace = apps.get_model('station_access', 'VncWorkspace')
    database = schema_editor.connection.alias
    rows = list(Workspace.objects.using(database).order_by('created_at', 'id'))
    if not rows:
        Workspace.objects.using(database).create(number=1, name='Workspace 1',
            application_name=getattr(settings, 'STATION_ACCESS_VNC_APPLICATION_NAME', 'vnc-workspace'), desired_running=False)
    for number, row in enumerate(rows, 1):
        row.number = number
        row.launch_pending = bool(row.launch_request_id and not row.runtime_id)
        # Never invent parameters for an already-issued legacy launch.
        if row.launch_pending:
            row.last_error = 'Legacy pending launch: resolve against its original controller before allocating an endpoint'
        row.save(using=database)


class Migration(migrations.Migration):
    dependencies = [('station_access', '0001_initial')]
    operations = [
        migrations.AlterField('vncworkspace', 'owner', models.ForeignKey(null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT, related_name='vnc_workspaces', to=settings.AUTH_USER_MODEL)),
        migrations.AlterField('vncworkspace', 'desired_running', models.BooleanField(default=False)),
        migrations.AddField('vncworkspace', 'number', models.PositiveIntegerField(null=True)),
        migrations.AddField('vncworkspace', 'display_number', models.PositiveIntegerField(null=True, blank=True, unique=True)),
        migrations.AddField('vncworkspace', 'launch_pending', models.BooleanField(default=False)),
        migrations.AddField('vncworkspace', 'launch_parameters', models.JSONField(default=dict, blank=True)),
        migrations.AddField('vncworkspace', 'endpoint_ready', models.BooleanField(default=False)),
        migrations.RunPython(initialize, migrations.RunPython.noop),
        migrations.AlterField('vncworkspace', 'number', models.PositiveIntegerField(unique=True)),
        migrations.AddConstraint('vncworkspace', models.UniqueConstraint(fields=('vnc_host', 'vnc_port'), name='unique_workspace_endpoint')),
    ]
