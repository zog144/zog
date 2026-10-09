from pathlib import Path
import os
import json

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_DIRECTORY = Path.home() / ".local" / "state" / "station-access"
STATE_DIRECTORY = Path(os.environ.get("STATION_ACCESS_STATE_DIRECTORY", DEFAULT_STATE_DIRECTORY))
STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)

_secrets_path = STATE_DIRECTORY / "deployment-secrets.json"
_deployment_secrets = json.loads(_secrets_path.read_text()) if _secrets_path.exists() else {}
SECRET_KEY = os.environ.get("STATION_ACCESS_SECRET_KEY", _deployment_secrets.get("django_secret_key", "station-access-development-only-secret"))
DEBUG = os.environ.get("STATION_ACCESS_DEBUG", "0") == "1"
ALLOWED_HOSTS = [item for item in os.environ.get("STATION_ACCESS_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if item]
CSRF_TRUSTED_ORIGINS = [item for item in os.environ.get("STATION_ACCESS_CSRF_TRUSTED_ORIGINS", "").split(",") if item]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "zog.station_access.apps.StationAccessConfig",
    "zog.station_access.host_registry.apps.HostRegistryConfig",
    "zog.station_access.archive_inventory.apps.ArchiveInventoryConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "zog.station_access.project.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "zog.station_access.project.wsgi.application"
ASGI_APPLICATION = "zog.station_access.project.asgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": STATE_DIRECTORY / "station-access.sqlite3", "OPTIONS": {"timeout":30}}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# This is deliberately an adapter factory rather than direct imports throughout Django.
STATION_ACCESS_BOX_CONTROL_GATEWAY_FACTORY = os.environ.get(
    "STATION_ACCESS_BOX_CONTROL_GATEWAY_FACTORY",
    "zog.station_access.box_control.current:create_gateway",
)

STATION_ACCESS_ZOG_PROJECT_DIRECTORY = os.environ.get("STATION_ACCESS_ZOG_PROJECT_DIRECTORY", "")
STATION_ACCESS_VNC_APPLICATION_NAME = os.environ.get("STATION_ACCESS_VNC_APPLICATION_NAME", "vnc-workspace")
STATION_ACCESS_VNC_TOKEN_TTL_SECONDS = int(os.environ.get("STATION_ACCESS_VNC_TOKEN_TTL_SECONDS", "120"))
STATION_ACCESS_WEBSOCKIFY_RESOLUTION_SECRET = os.environ.get("STATION_ACCESS_WEBSOCKIFY_RESOLUTION_SECRET", _deployment_secrets.get("websockify_secret", "development-websockify-secret"))
STATION_ACCESS_NOVNC_PATH = os.environ.get("STATION_ACCESS_NOVNC_PATH", "/novnc/vnc.html")
STATION_ACCESS_WEBSOCKIFY_PATH = os.environ.get("STATION_ACCESS_WEBSOCKIFY_PATH", "websockify")

# First pass: one station-access deployment and one private VNC network scope.
STATION_ACCESS_VNC_HOST = os.environ.get("STATION_ACCESS_VNC_HOST", "127.0.0.1")
STATION_ACCESS_DISPLAY_MINIMUM = int(os.environ.get("STATION_ACCESS_DISPLAY_MINIMUM", "1"))
STATION_ACCESS_DISPLAY_MAXIMUM = int(os.environ.get("STATION_ACCESS_DISPLAY_MAXIMUM", "999"))
STATION_ACCESS_VNC_PORT_BASE = int(os.environ.get("STATION_ACCESS_VNC_PORT_BASE", "5900"))

STATION_ACCESS_LOG_READER_FACTORY = os.environ.get("STATION_ACCESS_LOG_READER_FACTORY", "zog.station_access.box_control.journal:create_reader")

STATION_ACCESS_FRONTEND_DIRECTORY = Path(os.environ.get("STATION_ACCESS_FRONTEND_DIRECTORY", STATE_DIRECTORY / "frontend" / "dist"))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.environ.get("STATION_ACCESS_SECURE_COOKIES", "0") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Enabled only behind the deployment proxy, which replaces this header.
if os.environ.get("STATION_ACCESS_TRUST_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

STATIC_ROOT = STATE_DIRECTORY / "static"

HOST_DNS_CONFIGURATION = os.environ.get('HOST_DNS_CONFIGURATION', '')

# One canonical external origin for signed machine endpoints. Forwarded headers are not trusted.
HOST_IDENTITY_ORIGIN = os.environ.get("HOST_IDENTITY_ORIGIN", "")
HOST_ARCHIVE_CONFIGURATION = os.environ.get("HOST_ARCHIVE_CONFIGURATION", "")
HOST_PENDING_LIMIT = 1000
HOST_REPLAY_LIMIT = 10000
HOST_ENROLLMENT_PER_MINUTE = 60
HOST_ENROLLMENT_PER_ADDRESS = 10
# Vault keyring is a local owner-only JSON file, separate from database/archives.
HOST_VAULT_CONFIGURATION = os.environ.get('HOST_VAULT_CONFIGURATION', '')
HOST_MIRROR_LIMIT = 32
HOST_ROLE_LEASE_SECONDS = 900

# Optional archive-mirror provider integration.
ARCHIVE_MIRROR_CONFIGURATION = os.environ.get("ARCHIVE_MIRROR_CONFIGURATION", "")
if ARCHIVE_MIRROR_CONFIGURATION:
    INSTALLED_APPS.append("zog.archive_mirror.apps.ArchiveMirrorConfig")

# Enable only after installing the corrected workspace controller and passing local
# desktop/client/proxy acceptance. Source publication alone never enables launches.
STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED = os.environ.get("STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED", "0") == "1"

# Explicit operator enablement; the worker uses the station AWS SDK credentials.
HOST_DEPLOY_JOBS_ENABLED = os.environ.get("HOST_DEPLOY_JOBS_ENABLED", "0") == "1"

# Managed admission is unavailable until a dedicated control signer and authority
# UUID are configured. Never reuse archive or rootfs release-signing keys.
HOST_MANAGED_AUTHORITY_ID = os.environ.get('HOST_MANAGED_AUTHORITY_ID', '')
HOST_MANAGED_SIGNING_KEY_FILE = os.environ.get('HOST_MANAGED_SIGNING_KEY_FILE', '')

# Explicit managed beacon session opt-in. Dedicated signer and authority remain
# required by the endpoint; commands and archive delivery are not enabled here.
HOST_MANAGED_ADMISSION_ENABLED = os.environ.get("HOST_MANAGED_ADMISSION_ENABLED", "0") == "1"

# Optional atomic versioned frontend selection; takes precedence over the legacy directory.
STATION_ACCESS_FRONTEND_INSTALLATION = os.environ.get("STATION_ACCESS_FRONTEND_INSTALLATION", "")
