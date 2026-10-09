# Example for the host-derived acceptance fixture, not automatic production deployment.
# The generation supplies Python/native libraries, these scripts, wheels and frontend assets.
application(
    name="station-access",
    persistent=True,
    multiple_instances=False,
    start_policy="externally-controlled",
    writable_mounts=("data", "python"),
    preparation_revision="1",
    preparation=(program(
        name="prepare",
        command=("/usr/bin/python3.12", "-B", "/opt/acceptance/prepare.py"),
        execution_timeout_seconds=600,
        user="regular",
        mounts={"data": "/var/lib/station-access", "python": "/opt/station-python"},
        environment={"DJANGO_SETTINGS_MODULE": "station_access_project.settings", "STATION_ACCESS_STATE_DIRECTORY": "/var/lib/station-access", "ARCHIVE_MIRROR_CONFIGURATION": "/var/lib/station-access/archive-configuration.json"},
    ),),
    programs=(
        program(
            name="web",
            command=("/usr/bin/python3.12", "-B", "/opt/acceptance/entry.py", "web"),
            user="regular",
            mounts={"data": "/var/lib/station-access", "python": "/opt/station-python"},
            environment={"DJANGO_SETTINGS_MODULE": "station_access_project.settings", "STATION_ACCESS_STATE_DIRECTORY": "/var/lib/station-access", "STATION_ACCESS_FRONTEND_DIRECTORY": "/opt/station-frontend", "STATION_ACCESS_DEBUG": "0", "STATION_ACCESS_ALLOWED_HOSTS": "localhost,127.0.0.1", "ARCHIVE_MIRROR_CONFIGURATION": "/var/lib/station-access/archive-configuration.json"},
        ),
        program(
            name="archive-scheduler",
            command=("/usr/bin/python3.12", "-B", "/opt/acceptance/entry.py", "scheduler"),
            user="regular",
            mounts={"data": "/var/lib/station-access", "python": "/opt/station-python"},
            environment={"DJANGO_SETTINGS_MODULE": "station_access_project.settings", "STATION_ACCESS_STATE_DIRECTORY": "/var/lib/station-access", "ARCHIVE_MIRROR_CONFIGURATION": "/var/lib/station-access/archive-configuration.json"},
        ),
    ),
)
