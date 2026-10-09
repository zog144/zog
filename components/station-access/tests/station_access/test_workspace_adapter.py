"""Station services against the real workspace-v1 facade with simulated systemd/image IO."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from zog.station_access.box_control.current import CurrentBoxControlGateway
from zog.station_access.box_control.port import BoxControlUnavailable
from zog.station_access.models import ApplicationOwnership, WorkspaceApplicationLaunch
from zog.station_access.services.workspaces import create_workspace, ensure_workspace_ready, stop_workspace, delete_workspace, WorkspaceOperationError
from zog.station_access.services.workspace_applications import launch_application, application_members
from zog.station_access.services.vnc import issue_vnc_grant, resolve_vnc_target


@override_settings(STATION_ACCESS_VNC_APPLICATION_NAME='desktop')
class WorkspaceAdapterTests(TestCase):
    def setUp(self):
        from zog.box_control.specification import discover_applications
        from .controller_fixture import create_controller
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        control, transport = create_controller(Path(directory.name))
        self.control, self.transport = control, transport
        self.gateway = CurrentBoxControlGateway.__new__(CurrentBoxControlGateway)
        self.gateway._control = control
        self.gateway._discover_applications = discover_applications
        self.user = get_user_model().objects.create_user('workspace-owner')
        self.workspace = create_workspace(owner=self.user, name='Work')
        ApplicationOwnership.objects.create(application_name='terminal', owner=self.user)
        self.client.force_login(self.user)
        mock = patch('zog.station_access.api.views.get_gateway', return_value=self.gateway)
        mock.start(); self.addCleanup(mock.stop)

    def url(self, tail=''):
        return f'/api/workspaces/{self.workspace.pk}/applications/{tail}'

    def ready(self):
        return ensure_workspace_ready(self.workspace, self.gateway)

    def test_first_visit_registers_once_and_returns_private_unix_grant(self):
        runtime = self.ready()
        assert self.ready().runtime_id == runtime.runtime_id
        assert len(self.transport.started) == 1
        grant = issue_vnc_grant(self.user, self.workspace, self.gateway)
        assert resolve_vnc_target(grant.token, self.gateway) == ('unix_socket', '/run/zog/test/vnc.sock')
        assert '/run/zog' not in grant.novnc_url
        response = self.client.get('/internal/websockify-target/development-websockify-secret/', {'token':grant.token})
        assert response.json() == {'host':'unix_socket','port':'/run/zog/test/vnc.sock'}
        stop_workspace(self.workspace, self.gateway)
        assert resolve_vnc_target(grant.token, self.gateway) is None

    def test_endpoint_change_and_foreign_incarnation_reject_old_grant(self):
        self.ready(); grant = issue_vnc_grant(self.user, self.workspace, self.gateway)
        value = self.gateway.workspace_desktop_access(str(self.workspace.pk))
        with patch.object(self.gateway, 'workspace_desktop_access', return_value=dict(value, desktop_runtime_id='wrong')):
            assert resolve_vnc_target(grant.token, self.gateway) is None
        with patch.object(self.gateway, 'workspace_desktop_access', return_value=dict(value, vnc_endpoint={'kind':'unix','path':'/run/changed','browser_direct':False})):
            assert resolve_vnc_target(grant.token, self.gateway) is None

    def test_legacy_launch_evidence_is_preserved(self):
        self.workspace.launch_request_id = 'old-request'
        self.workspace.launch_pending = True
        self.workspace.launch_parameters = {'workspace-number':self.workspace.number, 'vnc-port':5901}
        self.workspace.save()
        with self.assertRaisesMessage(WorkspaceOperationError, 'Legacy'):
            self.ready()
        self.workspace.refresh_from_db()
        assert self.workspace.launch_request_id == 'old-request' and self.workspace.launch_pending
        assert not self.transport.started

    def test_pending_cancellation_never_clears_or_replaces_request(self):
        self.ready()
        self.workspace.launch_pending = True; self.workspace.save()
        request = self.workspace.launch_request_id
        with patch.object(self.gateway, 'cancel_application_launch', return_value={'status':'uncertain','runtime_id':None}):
            with self.assertRaisesMessage(WorkspaceOperationError, 'unresolved'):
                stop_workspace(self.workspace, self.gateway)
        self.workspace.refresh_from_db()
        assert self.workspace.launch_pending and self.workspace.launch_request_id == request

    def test_accepted_cancel_resolves_exact_runtime_then_stops(self):
        self.ready()
        self.workspace.launch_pending = True; self.workspace.runtime_id = None; self.workspace.save()
        stop_workspace(self.workspace, self.gateway)
        self.workspace.refresh_from_db()
        assert not self.workspace.launch_pending
        assert self.gateway.get_current_runtime(self.workspace.runtime_id).terminal

    def test_queued_claims_protect_delete_and_are_visible_without_private_ids(self):
        self.ready()
        request = self.control.request_application_launch('terminal', workspace_id=str(self.workspace.pk))
        response = self.client.get(self.url())
        assert response.status_code == 200, response.content
        data = response.json()
        assert data['membership']['authoritative'] and data['membership']['pending_count'] == 1
        assert request.request_id not in response.content.decode()
        self.workspace.refresh_from_db()
        with self.assertRaisesMessage(WorkspaceOperationError, 'pending'):
            delete_workspace(self.workspace, self.gateway, revision=self.workspace.updated_at.isoformat())

    def test_delete_calls_controller_tombstone_before_local_removal(self):
        self.ready(); identifier = str(self.workspace.pk)
        self.workspace.refresh_from_db()
        delete_workspace(self.workspace, self.gateway, revision=self.workspace.updated_at.isoformat())
        assert self.control.workspace_status(identifier)['state'] == 'deleted'

    def test_default_launch_gate_has_no_lifecycle_effects(self):
        response = self.client.post(self.url('launch/'), {'application':'terminal','action_id':str(uuid4())}, content_type='application/json')
        assert response.status_code == 409 and response.json()['error'] == 'workspace_acceptance_pending'
        assert not self.transport.started and not WorkspaceApplicationLaunch.objects.exists()

    @override_settings(STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED=True)
    def test_lost_launch_reply_retries_same_controller_request(self):
        self.ready()
        action_id = str(uuid4())
        original = self.gateway.launch_application
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('lost reply')
        # Image/preparation suitability is an independent gate; simulate readiness.
        with patch.object(self.gateway, 'preflight_workspace_application', return_value={'status':'ready-to-attempt'}), patch.object(self.gateway, 'launch_application', side_effect=lost):
            response = self.client.post(self.url('launch/'), {'application':'terminal','action_id':action_id}, content_type='application/json')
        assert response.status_code == 503, response.content
        action = WorkspaceApplicationLaunch.objects.get(pk=action_id)
        assert action.state == 'uncertain'
        request = action.request_id
        response = self.client.post(self.url('launch/'), {'application':'terminal','action_id':action_id}, content_type='application/json')
        assert response.status_code == 200, response.content
        action.refresh_from_db()
        assert action.request_id == request and action.state == 'accepted'
        assert len(self.transport.started) == 2
        assert len(application_members(self.workspace, self.gateway, self.user)) == 1
        # An accepted duplicate never starts or probes a replacement desktop.
        with patch.object(self.gateway, 'launch_application', side_effect=AssertionError('duplicate')):
            assert self.client.post(self.url('launch/'), {'application':'terminal','action_id':action_id}, content_type='application/json').status_code == 200

    def test_membership_incomplete_page_is_not_empty_success(self):
        self.ready()
        with patch.object(self.control, 'workspace_membership', return_value={'schema':'zog-workspace-v1','workspace_id':str(self.workspace.pk),'complete':False,'items':[]}):
            with self.assertRaises(BoxControlUnavailable):
                self.gateway.workspace_membership(str(self.workspace.pk))

    def test_old_controller_cannot_accept_workspace_mutation(self):
        with patch.object(self.gateway, 'workspace_capabilities', return_value={'supported':False}):
            with self.assertRaises(BoxControlUnavailable):
                self.ready()
        assert not self.transport.started

    @override_settings(STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED=True)
    def test_cancel_pending_and_accepted_actions_have_distinct_outcomes(self):
        from zog.station_access.services.workspace_applications import cancel_launch
        self.ready()
        queued = self.control.request_application_launch('terminal', workspace_id=str(self.workspace.pk))
        action = WorkspaceApplicationLaunch.objects.create(workspace=self.workspace, application_name='terminal', request_id=queued.request_id)
        assert cancel_launch(self.workspace, self.gateway, self.user, action_id=action.pk) == 'cancelled'
        action.refresh_from_db()
        assert not action.runtime_id
        accepted = self.control.launch_application('terminal', workspace_id=str(self.workspace.pk), request_id=self.control.issue_application_request_id())
        action = WorkspaceApplicationLaunch.objects.create(workspace=self.workspace, application_name='terminal', request_id=accepted.request_id)
        assert cancel_launch(self.workspace, self.gateway, self.user, action_id=action.pk) == 'accepted'
        assert not self.gateway.get_current_runtime(accepted.runtime_id).terminal

    def test_history_survives_termination_and_repeat_stop_is_exact(self):
        from zog.station_access.services.workspace_applications import stop_application
        self.ready()
        runtime = self.control.launch_application('terminal', workspace_id=str(self.workspace.pk))
        assert stop_application(self.workspace, self.gateway, self.user, runtime.runtime_id).terminal
        assert stop_application(self.workspace, self.gateway, self.user, runtime.runtime_id).terminal
        assert runtime.runtime_id in [item.runtime_id for item in application_members(self.workspace, self.gateway, self.user)]

    @override_settings(STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED=True)
    def test_action_intent_conflict_and_permission_denial_do_not_submit(self):
        self.ready()
        original = WorkspaceApplicationLaunch.objects.create(workspace=self.workspace, application_name='other', request_id='saved-request')
        with self.assertRaisesMessage(WorkspaceOperationError, 'different intent'):
            launch_application(self.workspace, self.gateway, self.user, name='terminal', action_id=str(original.pk))
        user = get_user_model().objects.create_user('unrelated')
        self.client.force_login(user)
        with patch.object(self.gateway, 'launch_application', side_effect=AssertionError('unauthorized')):
            assert self.client.post(self.url('launch/'), {'application':'terminal','action_id':str(uuid4())}, content_type='application/json').status_code == 404
        assert len(self.transport.started) == 1

    @override_settings(STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED=True)
    def test_client_first_use_keeps_desktop_intent_after_lost_desktop_reply(self):
        original = self.gateway.launch_application
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('desktop reply lost')
        with patch.object(self.gateway, 'launch_application', side_effect=lost):
            with self.assertRaises(OSError):
                launch_application(self.workspace, self.gateway, self.user, name='terminal', action_id=str(uuid4()))
        self.workspace.refresh_from_db()
        assert self.workspace.desired_running and self.workspace.launch_pending
        request = self.workspace.launch_request_id
        self.ready()
        assert self.workspace.launch_request_id == request and len(self.transport.started) == 1

    def status_url(self):
        return f'/api/workspaces/{self.workspace.pk}/readiness/'

    def test_readiness_is_read_only_before_first_start(self):
        before = self.workspace.updated_at
        response = self.client.get(self.status_url())
        assert response.status_code == 200 and response['Cache-Control'] == 'no-store'
        data = response.json()
        assert data['controller'] == 'available' and data['desktop'] == 'not-verified'
        assert any(c['code'] == 'unknown-workspace' for c in data['preflight']['checks'])
        self.workspace.refresh_from_db()
        assert self.workspace.updated_at == before and not self.workspace.controller_schema
        assert not self.transport.started
        assert not WorkspaceApplicationLaunch.objects.exists()

    def test_readiness_verifies_display_without_exposing_private_paths(self):
        self.ready()
        response = self.client.get(self.status_url())
        assert response.json()['desktop'] == 'ready'
        assert response.json()['cleanup_pending'] is False and response.json()['cleanup_count'] == 0
        assert '/run/' not in response.content.decode() and 'vnc_endpoint' not in response.content.decode()
        assert len(self.transport.started) == 1
        with patch.object(self.gateway, 'workspace_desktop_access', side_effect=RuntimeError('secret /private')):
            data = self.client.get(self.status_url()).json()
        assert data['desktop'] == 'running'

    def test_readiness_preserves_pending_evidence_when_controller_unavailable(self):
        action = WorkspaceApplicationLaunch.objects.create(workspace=self.workspace, application_name='terminal', request_id='private-request', state='uncertain')
        self.workspace.launch_pending = True; self.workspace.launch_request_id = 'old-desktop'; self.workspace.save()
        with patch('zog.station_access.api.views.get_gateway', side_effect=RuntimeError('private secret')):
            response = self.client.get(self.status_url())
        data = response.json()
        assert data['controller'] == 'unavailable' and data['pending_count'] is None
        assert data['registration'] == 'legacy-recovery-required' and data['launch_pending']
        assert data['launch_actions'][0]['id'] == str(action.pk)
        assert 'private' not in response.content.decode() and 'old-desktop' not in response.content.decode()
        self.workspace.refresh_from_db()
        assert self.workspace.launch_request_id == 'old-desktop'

    def test_preflight_allowlists_messages_and_check_codes(self):
        raw = dict(schema=1, application='terminal', advisory=True, status='ready-to-attempt',
            checks=[dict(code='image-inputs', status='blocked', message='password /private/root'),
                    dict(code='secret-path', status='unknown-secret', message='secret')])
        with patch.object(self.gateway, 'preflight_workspace_application', return_value=raw):
            response = self.client.get(self.status_url(), {'application':'terminal'})
        data = response.json()
        assert data['status'] == 'blocked' and data['checks'][0]['title'] == 'Root filesystem'
        assert data['checks'][1]['code'] == 'other'
        assert 'secret' not in response.content.decode() and '/private' not in response.content.decode()
        assert not self.transport.started

    def test_readiness_checks_workspace_and_application_authorization(self):
        assert self.client.get(self.status_url(), {'application':'someone-elses-app'}).status_code == 404
        other = get_user_model().objects.create_user('other-status-owner')
        self.client.force_login(other)
        assert self.client.get(self.status_url()).status_code == 404
        self.client.logout()
        assert self.client.get(self.status_url()).status_code == 401

    def test_readiness_hides_other_application_recovery_actions(self):
        WorkspaceApplicationLaunch.objects.create(workspace=self.workspace, application_name='private-app', request_id='hidden')
        assert self.client.get(self.status_url()).json()['launch_actions'] == []

    def test_readiness_never_treats_cleanup_as_ready(self):
        from dataclasses import replace
        runtime = self.ready()
        with patch.object(self.gateway, 'get_current_runtime', return_value=replace(runtime, state="terminated", cleanup_pending=True)):
            data = self.client.get(self.status_url()).json()
        assert data['cleanup_pending'] is True and data['desktop'] != 'ready'
