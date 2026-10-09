from django.contrib.auth.models import AbstractBaseUser
from django.conf import settings

from zog.station_access.models import ApplicationOwnership, VncWorkspace


def accessible_application_names(user: AbstractBaseUser) -> set[str] | None:
    if user.is_superuser:
        return None
    return set(
        ApplicationOwnership.objects.filter(owner=user).values_list(
            "application_name", flat=True
        )
    )


def can_access_application(user: AbstractBaseUser, application_name: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return ApplicationOwnership.objects.filter(
        owner=user, application_name=application_name
    ).exists()


def can_access_runtime(user: AbstractBaseUser, runtime) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if runtime.application_name == settings.STATION_ACCESS_VNC_APPLICATION_NAME:
        return VncWorkspace.objects.filter(owner=user, runtime_id=runtime.runtime_id).exists()
    return can_access_application(user, runtime.application_name)
