from zog.station_access.host_registry import deployment_views
from zog.station_access.host_registry import user_views
from django.urls import include, path, re_path
from zog.station_access.web import portal, asset, licenses, build_inventory
from zog.station_access.host_registry import setup_views
from zog.station_access.host_registry.views import administrator
from zog.station_access.api.views import websockify_target

urlpatterns = [
    path("", portal, name="portal"),
    path("licenses/", licenses, name="frontend-licenses"),
    path("frontend-build.json", build_inventory, name="frontend-build-inventory"),
    path("assets/<path:filename>", asset, name="frontend-asset"),
    re_path(r"^(?P<route>workspaces/[^/]+/provenance)/?$", portal),
    re_path(r"^(?P<route>(?:users|clouds|setup|registries|deployments|administration|networks|workspaces|applications|runtimes|vnc|build-jobs|hosts|host-identities|generations)(?:/[^/]*)?)/?$", portal),
    path("api/users/", user_views.users),
    path("api/users/<int:user_id>/", user_views.users),
    path("api/setup/clouds/", setup_views.clouds),
    path("api/setup/clouds/<uuid:credential_id>/check/", setup_views.cloud_check),
    path("api/setup/readiness/", setup_views.readiness),
    path("api/setup/registries/<uuid:credential_id>/check/", setup_views.provider_check),
    path("api/setup/registries/", setup_views.registries),
    path("api/setup/deployment-jobs/", deployment_views.collection),
    path("api/setup/deployment-jobs/<uuid:job_id>/", deployment_views.action),
    path("api/setup/deployments/", setup_views.deployments),
    path("api/archives/", include("zog.station_access.archive_inventory.urls")),
    path("archives/", administrator(portal)),
    path("api/hosts/", include("zog.station_access.host_registry.urls")),
    path("api/", include("zog.station_access.api.urls")),
    # Do not expose /internal through the public reverse proxy in production.
    path("internal/websockify-target/<str:secret>/", websockify_target, name="websockify-target"),
]

from django.conf import settings
if getattr(settings, "ARCHIVE_MIRROR_CONFIGURATION", ""):
    urlpatterns += [path("", include("zog.archive_mirror.urls"))]
