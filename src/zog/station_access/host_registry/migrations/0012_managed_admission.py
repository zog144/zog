from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('host_registry','0011_dns_evidence')]
    operations=[migrations.CreateModel(name='ManagedAdmission',fields=[
        ('host',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,primary_key=True,serialize=False,to='host_registry.host')),
        ('fingerprint',models.CharField(max_length=64)),
        ('installation_id',models.UUIDField()),('state_volume_id',models.UUIDField()),
        ('authority_id',models.UUIDField()),('registry_id',models.CharField(max_length=64)),
        ('epoch',models.PositiveBigIntegerField(default=0)),('checkpoint',models.UUIDField()),
        ('request',models.JSONField()),('claims',models.JSONField())])]
