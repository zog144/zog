# Template only: requires the shared-storage/read-only-input mount contract in README.md.
# Do not deploy until the controller supports that contract and the generation passes preflight.
application(
    name="archive-mirror",
    start_policy="externally-controlled",
    multiple_instances=False,
    programs=(
        program(
            name="server",
            command=("/usr/bin/python3", "-B", "-m", "zog.archive_mirror", "serve", "--host", "127.0.0.1", "--port", "8080"),
            environment={"DJANGO_SETTINGS_MODULE": "zog.archive_mirror.settings", "ARCHIVE_MIRROR_STATE": "/var/lib/archive-mirror", "ARCHIVE_MIRROR_CONFIGURATION": "/etc/archive-mirror/configuration.json"},
            user="regular",
        ),
        program(
            name="refresh-scheduler",
            command=("/usr/bin/python3", "-B", "-m", "zog.archive_mirror", "scheduler"),
            environment={"DJANGO_SETTINGS_MODULE": "zog.archive_mirror.settings", "ARCHIVE_MIRROR_STATE": "/var/lib/archive-mirror", "ARCHIVE_MIRROR_CONFIGURATION": "/etc/archive-mirror/configuration.json"},
            user="regular",
        ),
    ),
)
