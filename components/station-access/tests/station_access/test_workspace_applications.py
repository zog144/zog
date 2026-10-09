from dataclasses import replace
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from zog.station_access.box_control.fixture import FixtureGateway
from zog.station_access.models import ApplicationOwnership
from zog.station_access.services.workspaces import create_workspace, start_workspace


class WorkspaceApplicationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner')
        self.other = get_user_model().objects.create_user('other')
        self.client.force_login(self.user)
        self.workspace = create_workspace(owner=self.user, name='Research')
        self.gateway = FixtureGateway()
        self.ownership = ApplicationOwnership.objects.create(owner=self.user, application_name='editor')
        self.runtime = self.gateway.launch_application('editor', request_id='editor-request', parameters={'workspace-number':self.workspace.number})
        self.gateway.launch_application('browser', request_id='browser-request', parameters={'workspace-number':self.workspace.number})
        self.gateway.launch_application('editor', request_id='another-workspace', parameters={'workspace-number':999})
        self.gateway_patch = patch('zog.station_access.api.views.get_gateway', return_value=self.gateway)
        self.gateway_patch.start(); self.addCleanup(self.gateway_patch.stop)

    def url(self, tail=''):
        return f'/api/workspaces/{self.workspace.pk}/applications/{tail}'

    def stop(self, runtime_id=None):
        identifier = runtime_id or self.runtime.runtime_id
        return self.client.post(self.url(f'{identifier}/stop/'), {'confirmed_runtime_id':identifier}, content_type='application/json')

    def test_panel_scopes_both_workspace_and_application_without_starting(self):
        with patch.object(self.gateway, 'launch_application', side_effect=AssertionError('read must not launch')):
            response = self.client.get(self.url())
        assert response.status_code == 200 and response['Cache-Control'] == 'no-store'
        data = response.json()
        assert [entry['name'] for entry in data['applications']] == ['editor']
        assert [entry['runtime_id'] for entry in data['runtimes']] == [self.runtime.runtime_id]
        assert not data['launch']['available'] and not data['membership']['authoritative']
        self.workspace.refresh_from_db()
        assert not self.workspace.desired_running and self.workspace.runtime_id is None

    def test_desktop_is_excluded_even_for_administrator(self):
        admin = get_user_model().objects.create_superuser('admin')
        self.client.force_login(admin)
        start_workspace(self.workspace, self.gateway)
        data = self.client.get(self.url()).json()
        assert self.workspace.application_name not in [entry['name'] for entry in data['applications']]
        assert self.workspace.runtime_id not in [entry['runtime_id'] for entry in data['runtimes']]
        assert self.stop(self.workspace.runtime_id).status_code == 404
        assert not self.gateway.get_runtime(self.workspace.runtime_id).terminal

    def test_foreign_workspace_denied_before_controller_call(self):
        self.client.force_login(self.other)
        with patch('zog.station_access.api.views.get_gateway', side_effect=AssertionError('authorize first')):
            assert self.client.get(self.url()).status_code == 404
            assert self.stop().status_code == 404
            assert self.client.post(self.url('launch/'), {'application':'editor'}, content_type='application/json').status_code == 404

    def test_launch_is_closed_without_readiness_or_mutation(self):
        with patch.object(self.gateway, 'launch_application', side_effect=AssertionError('no mutation before contract exists')):
            response = self.client.post(self.url('launch/'), {'application':'editor'}, content_type='application/json')
        assert response.status_code == 409 and response.json()['error'] == 'workspace_launch_not_supported'
        self.workspace.refresh_from_db()
        assert not self.workspace.desired_running and self.workspace.launch_request_id is None

    def test_stop_is_exact_and_retries_do_not_launch_or_stop_other_instances(self):
        response = self.stop()
        assert response.status_code == 200 and response.json()['stopped']
        assert not self.gateway.get_runtime('fixture-runtime-another-workspace').terminal
        with patch.object(self.gateway, 'terminate_application_runtime', side_effect=AssertionError('already stopped')):
            assert self.stop().json()['stopped']

    def test_stop_rejects_foreign_runtime_and_revoked_application_permission(self):
        assert self.stop('fixture-runtime-another-workspace').status_code == 404
        assert self.stop('fixture-runtime-browser-request').status_code == 404
        self.ownership.delete()
        assert self.stop().status_code == 404
        assert self.client.get(self.url()).json()['runtimes'] == []
        assert not self.gateway.get_runtime(self.runtime.runtime_id).terminal

    def test_stop_confirmation_and_csrf(self):
        assert self.client.post(self.url(f'{self.runtime.runtime_id}/stop/'), {}, content_type='application/json').status_code == 400
        client = Client(enforce_csrf_checks=True); client.force_login(self.user)
        assert client.post(self.url(f'{self.runtime.runtime_id}/stop/'), {'confirmed_runtime_id':self.runtime.runtime_id}, content_type='application/json').status_code == 403

    def test_stop_in_progress_does_not_claim_termination(self):
        with patch.object(self.gateway, 'terminate_application_runtime', return_value=self.runtime):
            response = self.stop()
        assert response.status_code == 200 and not response.json()['stopped']

    def test_failed_stop_and_missing_observation_are_not_success(self):
        with patch.object(self.gateway, 'terminate_application_runtime', side_effect=RuntimeError('failure')):
            assert self.stop().status_code == 503
        with patch.object(self.gateway, 'get_runtime', return_value=None):
            assert self.stop().status_code == 503
        with patch.object(self.gateway, 'get_runtime', return_value=replace(self.runtime, runtime_id='wrong-runtime')), patch.object(self.gateway, 'terminate_application_runtime', side_effect=AssertionError('do not stop with mismatched facts')):
            assert self.stop().status_code == 503

    def test_current_adapter_rejects_legacy_parameter_membership(self):
        from zog.station_access.box_control.current import CurrentBoxControlGateway
        from zog.station_access.box_control.port import BoxControlUnavailable
        from types import SimpleNamespace
        gateway = CurrentBoxControlGateway.__new__(CurrentBoxControlGateway)
        gateway._control = SimpleNamespace()
        with self.assertRaises(BoxControlUnavailable):
            gateway.workspace_application_runtimes(str(self.workspace.pk))
