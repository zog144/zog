import json
from urllib.parse import unquote
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from zog.station_access.box_control.fixture import _GATEWAY
from zog.station_access.models import ApplicationOwnership, VncAccessGrant, VncWorkspace
from zog.station_access.services.workspaces import bind_workspace_endpoint, reconcile_workspace

FIXTURE = "zog.station_access.box_control.fixture:create_gateway"


@override_settings(
    STATION_ACCESS_BOX_CONTROL_GATEWAY_FACTORY=FIXTURE,
    STATION_ACCESS_WEBSOCKIFY_RESOLUTION_SECRET="test-secret",
    STATION_ACCESS_VNC_APPLICATION_NAME="vnc-workspace",
)
class ApiTests(TestCase):
    def setUp(self):
        _GATEWAY.runtimes.clear()
        _GATEWAY.counter = 0
        _GATEWAY.parameters.clear()
        _GATEWAY.cancelled.clear()
        users = get_user_model()
        self.alice = users.objects.create_user(username="alice", password="secret")
        self.bob = users.objects.create_user(username="bob", password="secret")
        ApplicationOwnership.objects.create(application_name="browser", owner=self.alice)
        ApplicationOwnership.objects.create(application_name="editor", owner=self.bob)
        _GATEWAY.launch_application("browser", request_id="browser-alice")
        _GATEWAY.launch_application("editor", request_id="editor-bob")

    def create_workspace(self, name="Desk") -> VncWorkspace:
        self.client.force_login(self.alice)
        response = self.client.post(
            "/api/workspaces/create/",
            data=json.dumps({"name": name}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        workspace = VncWorkspace.objects.get(pk=response.json()["workspace"]["id"])
        response = self.client.post(f"/api/workspaces/{workspace.pk}/start/")
        self.assertEqual(response.status_code, 200, response.content)
        workspace.refresh_from_db()
        return workspace

    def test_unauthenticated_inspection_is_rejected(self):
        self.assertEqual(self.client.get("/api/applications/").status_code, 401)
        self.assertEqual(self.client.get("/api/workspaces/").status_code, 401)

    def test_application_list_is_filtered_by_owner(self):
        self.client.force_login(self.alice)
        response = self.client.get("/api/applications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([a["name"] for a in response.json()["applications"]], ["browser"])

    def test_runtime_list_is_filtered_by_application_owner(self):
        self.client.force_login(self.alice)
        response = self.client.get("/api/runtimes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [runtime["application_name"] for runtime in response.json()["runtimes"]],
            ["browser"],
        )

    def test_runtime_detail_hides_other_users_runtime(self):
        bob_runtime = next(r for r in _GATEWAY.runtimes.values() if r.application_name == "editor")
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(f"/api/runtimes/{bob_runtime.runtime_id}/").status_code,
            404,
        )

    def test_one_workspace_launches_one_vnc_runtime(self):
        workspace = self.create_workspace()
        self.assertTrue(workspace.desired_running)
        self.assertIsNotNone(workspace.launch_request_id)
        self.assertIsNotNone(workspace.runtime_id)
        runtime = _GATEWAY.get_runtime(workspace.runtime_id)
        self.assertEqual(runtime.application_name, "vnc-workspace")
        self.assertEqual(runtime.request_id, workspace.launch_request_id)

    def test_two_workspaces_launch_two_distinct_multi_instance_runtimes(self):
        first = self.create_workspace("Left")
        second = self.create_workspace("Right")
        self.assertNotEqual(first.launch_request_id, second.launch_request_id)
        self.assertNotEqual(first.runtime_id, second.runtime_id)
        self.assertNotEqual(first.instance_id, second.instance_id)

    def test_workspace_and_its_vnc_runtime_are_owner_scoped(self):
        workspace = self.create_workspace()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get("/api/workspaces/").json()["workspaces"], [])
        self.assertEqual(
            self.client.get(f"/api/runtimes/{workspace.runtime_id}/").status_code,
            404,
        )

    def test_desired_stopped_reconciliation_terminates_runtime_after_crash_window(self):
        workspace = self.create_workspace()
        runtime_id = workspace.runtime_id
        # Simulate a process crash after desired_running=False was committed but before
        # box-control terminate_application_runtime() was called.
        workspace.desired_running = False
        workspace.save(update_fields=("desired_running", "updated_at"))
        state = reconcile_workspace(workspace, _GATEWAY)
        self.assertEqual(state.status, "stopped")
        self.assertEqual(_GATEWAY.get_runtime(runtime_id).state, "terminated")

    def test_interrupted_launch_reuses_persisted_request_identity(self):
        workspace = VncWorkspace.objects.create(
            owner=self.alice,
            number=99,
            name="Interrupted",
            launch_pending=True,
            display_number=99, vnc_host="127.0.0.1", vnc_port=5999,
            launch_parameters={"workspace-number": 99, "display-number": 99, "vnc-port": 5999},
            application_name="vnc-workspace",
            desired_running=True,
            launch_request_id="fixture-request-interrupted",
        )
        first = reconcile_workspace(workspace, _GATEWAY)
        workspace.refresh_from_db()
        first_runtime_id = workspace.runtime_id
        # Losing only station-access's runtime binding must not create a second box-control
        # runtime; the same request id returns the historical launch.
        workspace.launch_pending = True
        workspace.runtime_id = None
        workspace.instance_id = None
        workspace.save(update_fields=("runtime_id", "instance_id", "launch_pending", "updated_at"))
        second = reconcile_workspace(workspace, _GATEWAY)
        workspace.refresh_from_db()
        self.assertEqual(first.runtime.runtime_id, second.runtime.runtime_id)
        self.assertEqual(workspace.runtime_id, first_runtime_id)

    def test_owner_can_issue_vnc_grant_and_raw_token_is_not_stored(self):
        workspace = self.create_workspace()
        bind_workspace_endpoint(workspace, host="127.0.0.1", port=5901)
        response = self.client.post(f"/api/workspaces/{workspace.pk}/vnc-grant/")
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertIn("token=", unquote(payload["novnc_url"]))
        grant = VncAccessGrant.objects.get()
        self.assertNotEqual(grant.token_digest, payload["token"])
        self.assertNotIn(payload["token"], grant.token_digest)

    def test_json_token_api_resolution_returns_host_and_port(self):
        workspace = self.create_workspace()
        bind_workspace_endpoint(workspace, host="127.0.0.1", port=5901)
        token = self.client.post(f"/api/workspaces/{workspace.pk}/vnc-grant/").json()["token"]
        self.client.logout()
        response = self.client.get(
            "/internal/websockify-target/test-secret/", {"token": token}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"host": "127.0.0.1", "port": 5901})

    def test_runtime_termination_invalidates_unresolved_grant(self):
        workspace = self.create_workspace()
        bind_workspace_endpoint(workspace, host="127.0.0.1", port=5901)
        token = self.client.post(f"/api/workspaces/{workspace.pk}/vnc-grant/").json()["token"]
        _GATEWAY.terminate_application_runtime(workspace.runtime_id)
        response = self.client.get(
            "/internal/websockify-target/test-secret/", {"token": token}
        )
        self.assertEqual(response.status_code, 404)

    def test_endpoint_rebinding_revokes_unresolved_grant(self):
        workspace = self.create_workspace()
        bind_workspace_endpoint(workspace, host="127.0.0.1", port=5901)
        token = self.client.post(f"/api/workspaces/{workspace.pk}/vnc-grant/").json()["token"]
        bind_workspace_endpoint(workspace, host="127.0.0.1", port=5902)
        response = self.client.get(
            "/internal/websockify-target/test-secret/", {"token": token}
        )
        self.assertEqual(response.status_code, 404)

    def test_workspace_stop_revokes_unresolved_grant(self):
        workspace = self.create_workspace()
        bind_workspace_endpoint(workspace, host="127.0.0.1", port=5901)
        token = self.client.post(f"/api/workspaces/{workspace.pk}/vnc-grant/").json()["token"]
        response = self.client.post(f"/api/workspaces/{workspace.pk}/stop/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["workspace"]["desired_running"])
        self.assertEqual(
            self.client.get(
                "/internal/websockify-target/test-secret/", {"token": token}
            ).status_code,
            404,
        )

    def test_vnc_grant_is_refused_until_display_is_ready(self):
        workspace = self.create_workspace()
        with patch.object(_GATEWAY, "workspace_ready", return_value=False):
            response = self.client.post(f"/api/workspaces/{workspace.pk}/vnc-grant/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "vnc_unavailable")

    def test_wrong_internal_secret_is_rejected(self):
        self.assertEqual(
            self.client.get(
                "/internal/websockify-target/wrong/", {"token": "anything"}
            ).status_code,
            404,
        )
