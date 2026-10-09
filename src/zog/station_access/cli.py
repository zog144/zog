"""Command-line launcher for station-access."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets


def _state_directory(value):
    if value:
        return Path(value).expanduser().resolve()
    configured = os.environ.get("STATION_ACCESS_STATE_DIRECTORY")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local" / "state" / "station-access").resolve()


def main():
    parser = argparse.ArgumentParser(description="Start the Zog station-access portal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--project", help="Trusted local Zog project directory")
    parser.add_argument("--state-directory", help="Persistent station-access state directory")
    parser.add_argument("--initialize-only", action="store_true")
    options = parser.parse_args()

    state = _state_directory(options.state_directory)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["STATION_ACCESS_STATE_DIRECTORY"] = str(state)
    os.environ.setdefault("STATION_ACCESS_DEBUG", "0")
    if options.project:
        os.environ["STATION_ACCESS_ZOG_PROJECT_DIRECTORY"] = str(Path(options.project).expanduser().resolve())

    with (state / "initialize.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = state / "deployment-secrets.json"
        if not config.exists():
            temporary = state / "deployment-secrets.new"
            with open(temporary, "w", opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
                json.dump(
                    {
                        "django_secret_key": secrets.token_urlsafe(48),
                        "websockify_secret": secrets.token_urlsafe(48),
                    },
                    handle,
                )
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(config)

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zog.station_access.project.settings")
        import django
        django.setup()
        from django.core.management import call_command
        call_command("migrate", interactive=False, verbosity=0)
        call_command("initialize_station")

    if options.initialize_only:
        return

    from django.conf import settings
    if not settings.STATION_ACCESS_FRONTEND_INSTALLATION:
        frontend = Path(settings.STATION_ACCESS_FRONTEND_DIRECTORY)
        if not (frontend / "index.html").is_file():
            parser.error(
                "Frontend installation missing: activate a four-stage frontend installation "
                "or set STATION_ACCESS_FRONTEND_DIRECTORY to a verified dist directory"
            )

    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    print(f"Station-access is listening on http://{options.host}:{options.port}", flush=True)
    serve(
        get_wsgi_application(),
        host=options.host,
        port=options.port,
        threads=8,
        max_request_body_size=1024 * 1024,
        channel_timeout=60,
    )
