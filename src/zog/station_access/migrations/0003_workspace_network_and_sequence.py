from django.db import migrations, models
from django.db.models import Max


def initialize_sequence(apps, schema_editor):
    alias = schema_editor.connection.alias
    maximum = apps.get_model('station_access', 'VncWorkspace').objects.using(alias).aggregate(value=Max('number'))['value'] or 0
    apps.get_model('station_access', 'WorkspaceNumberSequence').objects.using(alias).create(pk=1, next_number=maximum + 1)


class Migration(migrations.Migration):
    dependencies = [('station_access', '0002_lazy_workspaces')]
    operations = [
        migrations.AddField(model_name='vncworkspace', name='network', field=models.CharField(default='default', max_length=64)),
        migrations.CreateModel(name='WorkspaceNumberSequence', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('next_number', models.PositiveIntegerField(default=2))]),
        migrations.RunPython(initialize_sequence, migrations.RunPython.noop),
    ]
