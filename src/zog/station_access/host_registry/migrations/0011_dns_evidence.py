from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('host_registry', '0010_deployment_jobs')]
    operations = [
        migrations.AddField(model_name='host', name='signed_dns_report', field=models.JSONField(default=dict)),
        migrations.AddField(model_name='host', name='signed_dns_fingerprint', field=models.CharField(max_length=64, blank=True)),
        migrations.AddField(model_name='host', name='signed_dns_observed_at', field=models.DateTimeField(null=True, blank=True)),
    ]
