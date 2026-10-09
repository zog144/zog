from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('host_registry', '0005_mirrorrole_stationcredential')]
    operations = [
        migrations.AddField(model_name='host', name='archived_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='host', name='archived_by', field=models.CharField(blank=True, max_length=150)),
    ]
