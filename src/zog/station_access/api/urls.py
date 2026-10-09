from django.urls import path

from . import views

urlpatterns = [
    path("build-jobs/", views.build_jobs, name="build-jobs"),
    path("build-jobs/<str:job_id>/", views.build_job_detail, name="build-job-detail"),
    path("build-jobs/<str:job_id>/logs/", views.build_job_logs, name="build-job-logs"),
    path("session/", views.session, name="session"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("applications/", views.applications, name="applications"),
    path("runtimes/", views.runtimes, name="runtimes"),
    path("runtimes/<str:runtime_id>/logs/", views.runtime_logs, name="runtime-logs"),
    path("runtimes/<str:runtime_id>/", views.runtime_detail, name="runtime-detail"),
    path("workspaces/", views.workspaces, name="workspaces"),
    path("workspaces/<uuid:workspace_id>/readiness/", views.workspace_readiness, name="workspace-readiness"),
    path("workspaces/<uuid:workspace_id>/provenance/", views.workspace_provenance, name="workspace-provenance"),
    path("workspaces/<uuid:workspace_id>/", views.workspace_detail, name="workspace-detail"),
    path("workspaces/<uuid:workspace_id>/update/", views.workspace_update, name="workspace-update"),
    path("workspaces/<uuid:workspace_id>/delete/", views.workspace_delete, name="workspace-delete"),
    path("workspaces/<uuid:workspace_id>/applications/", views.workspace_applications, name="workspace-applications"),
    path("workspaces/<uuid:workspace_id>/applications/launches/<uuid:action_id>/cancel/", views.workspace_application_cancel, name="workspace-application-cancel"),
    path("workspaces/<uuid:workspace_id>/applications/launch/", views.workspace_application_launch, name="workspace-application-launch"),
    path("workspaces/<uuid:workspace_id>/applications/<str:runtime_id>/stop/", views.workspace_application_stop, name="workspace-application-stop"),
    path("workspaces/create/", views.workspace_create, name="workspace-create"),
    path("workspaces/<uuid:workspace_id>/start/", views.workspace_start, name="workspace-start"),
    path("workspaces/<uuid:workspace_id>/stop/", views.workspace_stop, name="workspace-stop"),
    path("workspaces/<uuid:workspace_id>/reconcile/", views.workspace_reconcile, name="workspace-reconcile"),
    path("workspaces/<uuid:workspace_id>/vnc-grant/", views.workspace_vnc_grant, name="workspace-vnc-grant"),
]
