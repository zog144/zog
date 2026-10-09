from django.db import migrations

def seed(apps,schema_editor):
    apps.get_model('host_registry','SecurityGate').objects.get_or_create(pk=1)

class Migration(migrations.Migration):
    dependencies=[('host_registry','0003_admissionwindow_archivepolicy_enrollmentrequest_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
