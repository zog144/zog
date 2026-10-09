from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from django.db import transaction
from .models import VncWorkspace


def assign_default(database):
    # Initialization precedes account setup; never award it to an arbitrary ordinary user.
    administrator = get_user_model().objects.using(database).filter(is_superuser=True, is_active=True).order_by('pk').first()
    if administrator:
        with transaction.atomic(using=database):
            VncWorkspace.objects.using(database).filter(number=1, owner=None).update(owner=administrator)


@receiver(post_save, sender=get_user_model())
def user_saved(sender, instance, using, **kwargs):
    if instance.is_superuser and instance.is_active:
        assign_default(using)


@receiver(post_migrate)
def migrated(sender, using, **kwargs):
    if sender.name == 'station_access':
        assign_default(using)
