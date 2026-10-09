from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('archive_inventory', '0001_initial')]
    operations = [migrations.AddField(model_name='observation', name='schema_version', field=models.PositiveIntegerField(default=1)), migrations.CreateModel(name='NoticeBundle', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('host', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='host_registry.host')),
        ('collection', models.CharField(max_length=64)), ('digest', models.CharField(max_length=64)),
        ('bundle_digest', models.CharField(max_length=64)), ('size', models.PositiveIntegerField()),
        ('evidence', models.JSONField()),
    ], options={'constraints': [models.UniqueConstraint(fields=('host', 'collection', 'digest'), name='archive_notice_binding')]})]
