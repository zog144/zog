from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from zog.station_access.archive_inventory.models import Entry, Observation
from zog.station_access.host_registry.models import Host
from zog.station_access.box_control.fixture import FixtureGateway
from zog.station_access.models import ApplicationOwnership
from zog.station_access.services.workspaces import create_workspace, start_workspace


class WorkspaceProvenanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner")
        self.admin = get_user_model().objects.create_superuser("admin")
        self.other = get_user_model().objects.create_user("other")
        ApplicationOwnership.objects.create(owner=self.user, application_name="editor")
        self.workspace = create_workspace(owner=self.user, name="Research")
        self.gateway = FixtureGateway()
        start_workspace(self.workspace, self.gateway)
        self.workspace.refresh_from_db()
        self.client_runtime = self.gateway.launch_application(
            "editor",
            request_id="editor-request",
            parameters={"workspace-number": self.workspace.number},
        )
        self.gateway.runtimes[self.client_runtime.runtime_id] = replace(
            self.client_runtime, generation="generation-old"
        )
        self.client.force_login(self.user)
        self.gateway_patch = patch("zog.station_access.api.views.get_gateway", return_value=self.gateway)
        self.gateway_patch.start()
        self.addCleanup(self.gateway_patch.stop)

    def url(self):
        return f"/api/workspaces/{self.workspace.pk}/provenance/"

    def archive(self, generation, digest, *, seconds=0):
        host = Host.objects.create(label=f"mirror-{digest[:6]}")
        observed = timezone.now() + timedelta(seconds=seconds)
        observation = Observation.objects.create(
            host=host,
            schema_version=2,
            role_revision=1,
            observed_at=observed,
            status="ok",
            serving=True,
            summary={},
            total=1,
            complete=True,
        )
        Entry.objects.create(
            observation=observation,
            position=0,
            collection="root-filesystems",
            digest=digest,
            metadata={
                "kind": "root-filesystem",
                "version": generation,
                "name": "Zog rootfs",
                "availability": "present",
                "provenance": "source-export",
                "approval": "approved",
            },
        )
        return observation

    def test_owner_sees_immutable_runtime_generation_without_admin_archive_locator(self):
        self.archive("generation-old", "a" * 64)
        with patch.object(self.gateway, "list_applications", side_effect=AssertionError("do not resolve current application spec")), \
             patch.object(self.gateway, "launch_application", side_effect=AssertionError("provenance read must not launch")):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        body = response.json()
        self.assertEqual(body["basis"], "immutable-runtime-history")
        runtime = next(item for item in body["runtimes"] if item["runtime_id"] == self.client_runtime.runtime_id)
        self.assertEqual(runtime["application"], "editor")
        self.assertEqual(runtime["generation"], "generation-old")
        self.assertEqual(runtime["generation_resolution"], "resolved")
        self.assertEqual(runtime["generation_digest"], "a" * 64)
        self.assertIsNone(runtime["generation_archive"])
        self.assertFalse(body["administrator_generation_details"])
        self.assertTrue(any(item["role"] == "desktop" for item in body["runtimes"]))

    def test_administrator_gets_exact_generation_detail_binding(self):
        observation = self.archive("generation-old", "b" * 64)
        self.client.force_login(self.admin)
        body = self.client.get(self.url()).json()
        runtime = next(item for item in body["runtimes"] if item["runtime_id"] == self.client_runtime.runtime_id)
        self.assertTrue(body["administrator_generation_details"])
        self.assertEqual(runtime["generation_resolution"], "resolved")
        self.assertEqual(runtime["generation_archive"], {
            "mirror": str(observation.host_id),
            "snapshot": str(observation.pk),
            "collection": "root-filesystems",
            "digest": "b" * 64,
            "observed_at": observation.observed_at.isoformat(),
        })

    def test_conflicting_generation_digests_are_not_resolved(self):
        self.archive("generation-old", "c" * 64)
        self.archive("generation-old", "d" * 64, seconds=1)
        self.client.force_login(self.admin)
        body = self.client.get(self.url()).json()
        runtime = next(item for item in body["runtimes"] if item["runtime_id"] == self.client_runtime.runtime_id)
        self.assertEqual(runtime["generation_resolution"], "conflict")
        self.assertEqual(runtime["generation_candidate_count"], 2)
        self.assertIsNone(runtime["generation_digest"])
        self.assertIsNone(runtime["generation_archive"])

    def test_foreign_workspace_is_hidden_before_controller_access(self):
        self.client.force_login(self.other)
        with patch("zog.station_access.api.views.get_gateway", side_effect=AssertionError("authorize first")):
            self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_browser_route_resolves_without_starting_workspace(self):
        from django.urls import resolve
        from zog.station_access.web import portal
        match = resolve(f"/workspaces/{self.workspace.pk}/provenance")
        self.assertIs(match.func, portal)

    def test_never_registered_workspace_has_empty_history(self):
        workspace = create_workspace(owner=self.user, name="Fresh")
        class CurrentLikeGateway:
            def workspace_capabilities(self):
                return {"supported": True}
            def workspace_application_runtimes(self, selector):
                raise AssertionError("unregistered workspace must not inspect controller membership")
            def get_runtime(self, runtime_id):
                raise AssertionError("fresh workspace has no runtime")
        with patch("zog.station_access.api.views.get_gateway", return_value=CurrentLikeGateway()):
            body = self.client.get(f"/api/workspaces/{workspace.pk}/provenance/").json()
        self.assertEqual(body["runtimes"], [])

    def test_revoked_application_permission_hides_client_but_not_workspace_desktop(self):
        ApplicationOwnership.objects.filter(owner=self.user, application_name="editor").delete()
        body = self.client.get(self.url()).json()
        self.assertNotIn(self.client_runtime.runtime_id, [item["runtime_id"] for item in body["runtimes"]])
        self.assertIn(self.workspace.runtime_id, [item["runtime_id"] for item in body["runtimes"]])
