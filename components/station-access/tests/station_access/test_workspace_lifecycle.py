from dataclasses import replace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
from pathlib import Path
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from zog.station_access.models import VncWorkspace
from zog.station_access.box_control.fixture import FixtureGateway
from zog.station_access.services.workspaces import (create_workspace, start_workspace, stop_workspace,
    reconcile_workspace, ensure_workspace_ready, WorkspaceOperationError, require_workspace_number)
from zog.station_access.services.locks import workspace_lock


class LifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner')
        self.gateway = FixtureGateway()
        self.workspace = create_workspace(owner=self.user, name='Desk')

    def test_creation_is_lazy_and_number_stable(self):
        assert not self.workspace.desired_running
        assert self.workspace.runtime_id is None
        assert self.workspace.display_number is None
        assert self.gateway.runtimes == {}
        reconcile_workspace(self.workspace, self.gateway)
        assert self.gateway.runtimes == {}

    def test_initial_workspace_is_dormant_and_claimed_by_first_admin(self):
        initial = VncWorkspace.objects.get(number=1)
        assert initial.owner_id is None and not initial.desired_running
        admin = get_user_model().objects.create_superuser('admin', password='test')
        initial.refresh_from_db()
        assert initial.owner_id == admin.pk
        get_user_model().objects.create_superuser('other', password='test')
        initial.refresh_from_db()
        assert initial.owner_id == admin.pk

    def test_two_workspaces_get_distinct_persistent_allocations(self):
        second = create_workspace(owner=self.user, name='Other')
        first_runtime = start_workspace(self.workspace, self.gateway)
        start_workspace(second, self.gateway)
        assert self.workspace.vnc_port != second.vnc_port
        assert self.workspace.display_number != second.display_number
        port = self.workspace.vnc_port
        assert start_workspace(self.workspace, self.gateway) == first_runtime
        stop_workspace(self.workspace, self.gateway)
        restarted = start_workspace(self.workspace, self.gateway)
        assert restarted.runtime_id != first_runtime.runtime_id
        assert self.workspace.vnc_port == port

    def test_lost_launch_reply_then_stop_recovers_exact_runtime(self):
        launch = self.gateway.launch_application
        def lose_reply(*args, **kwargs):
            launch(*args, **kwargs)
            raise RuntimeError('lost response')
        with patch.object(self.gateway, 'launch_application', side_effect=lose_reply):
            with self.assertRaises(RuntimeError):
                start_workspace(self.workspace, self.gateway)
        assert self.workspace.launch_pending and self.workspace.runtime_id is None
        stop_workspace(self.workspace, self.gateway)
        assert len(self.gateway.runtimes) == 1
        assert all(r.terminal for r in self.gateway.runtimes.values())
        assert not self.workspace.launch_pending

    def test_crash_before_submit_then_stop_never_launches(self):
        with patch.object(self.gateway, 'launch_application', side_effect=RuntimeError('before submit')):
            with self.assertRaises(RuntimeError):
                start_workspace(self.workspace, self.gateway)
        stop_workspace(self.workspace, self.gateway)
        assert not self.gateway.runtimes
        assert not self.workspace.launch_pending

    def test_lost_reply_then_retry_uses_same_identity(self):
        first = start_workspace(self.workspace, self.gateway)
        self.workspace.runtime_id = None
        self.workspace.launch_pending = True
        self.workspace.save()
        assert start_workspace(self.workspace, self.gateway).runtime_id == first.runtime_id
        assert len(self.gateway.runtimes) == 1

    def test_expired_pending_identity_blocks_without_replacement(self):
        with patch.object(self.gateway, 'launch_application', side_effect=RuntimeError('expired identity')):
            with self.assertRaises(RuntimeError):
                start_workspace(self.workspace, self.gateway)
            request = self.workspace.launch_request_id
            with self.assertRaises(RuntimeError):
                reconcile_workspace(self.workspace, self.gateway)
        assert self.workspace.launch_request_id == request
        assert not self.gateway.runtimes

    def test_replacement_revokes_grants_and_requires_readiness(self):
        ensure_workspace_ready(self.workspace, self.gateway)
        from zog.station_access.services.vnc import issue_vnc_grant, resolve_vnc_target
        grant = issue_vnc_grant(self.user, self.workspace, self.gateway)
        self.gateway.terminate_application_runtime(self.workspace.runtime_id)
        start_workspace(self.workspace, self.gateway)
        assert not self.workspace.endpoint_ready
        assert resolve_vnc_target(grant.token, self.gateway) is None

    def test_requirement_is_authorized_and_waits_for_display(self):
        other = get_user_model().objects.create_user('other')
        with self.assertRaises(VncWorkspace.DoesNotExist):
            require_workspace_number(user=other, number=self.workspace.number, gateway=self.gateway)
        with patch.object(self.gateway, 'workspace_ready', return_value=False):
            with self.assertRaises(WorkspaceOperationError):
                require_workspace_number(user=self.user, number=self.workspace.number, gateway=self.gateway)
        assert self.workspace.__class__.objects.get(pk=self.workspace.pk).desired_running
        result = require_workspace_number(user=self.user, number=self.workspace.number, gateway=self.gateway)
        assert result.endpoint_ready
        assert len(self.gateway.runtimes) == 1


class LockTests(SimpleTestCase):
    def test_threads_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STATE_DIRECTORY=Path(directory)):
            active = []
            def operation(number):
                with workspace_lock('same-workspace'):
                    assert not active
                    active.append(number)
                    time.sleep(.02)
                    active.remove(number)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(operation, range(8)))


from django.test import TransactionTestCase
from django.db import close_old_connections
import threading

class ConcurrentLaunchTests(TransactionTestCase):
    def test_simultaneous_first_use_creates_one_runtime(self):
        user = get_user_model().objects.create_user('concurrent-owner')
        workspace = create_workspace(owner=user, name='Concurrent')
        gateway = FixtureGateway()
        barrier = threading.Barrier(2)
        def launch():
            close_old_connections()
            local = VncWorkspace.objects.get(pk=workspace.pk)
            barrier.wait(timeout=5)
            try:
                return start_workspace(local, gateway).runtime_id
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: launch(), range(2)))
        assert results[0] == results[1]
        assert len(gateway.runtimes) == 1

class RetainedRuntimeTests(TestCase):
    def test_recovery_finds_runtime_without_replaying_expired_identity(self):
        user = get_user_model().objects.create_user('retained-owner')
        workspace = create_workspace(owner=user, name='Retained')
        gateway = FixtureGateway()
        first = start_workspace(workspace, gateway)
        workspace.runtime_id = None
        workspace.launch_pending = True
        workspace.save()
        with patch.object(gateway, 'launch_application', side_effect=AssertionError('must not replay')):
            assert start_workspace(workspace, gateway).runtime_id == first.runtime_id
