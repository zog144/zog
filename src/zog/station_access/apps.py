from django.apps import AppConfig

class StationAccessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "zog.station_access"
    label = "station_access"

    def ready(self):
        from . import signals  # noqa: F401
