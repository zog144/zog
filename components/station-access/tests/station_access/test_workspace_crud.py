from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from zog.station_access.models import VncWorkspace
from zog.station_access.box_control.fixture import FixtureGateway
from zog.station_access.services.workspaces import create_workspace, start_workspace, delete_workspace, update_workspace, WorkspaceOperationError


class WorkspaceCrudTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner')
        self.other = get_user_model().objects.create_user('other')
        self.client.force_login(self.user)
        self.workspace = create_workspace(owner=self.user, name='Desk')
        self.gateway = FixtureGateway()

    def url(self, suffix=''):
        return f'/api/workspaces/{self.workspace.pk}/{suffix}'

    def test_rename_live_workspace_preserves_binding(self):
        start_workspace(self.workspace, self.gateway)
        binding = (self.workspace.number, self.workspace.runtime_id, self.workspace.launch_request_id, self.workspace.endpoint_revision)
        with patch('zog.station_access.api.views.get_gateway', side_effect=AssertionError('rename must not call controller')):
            response = self.client.post(self.url('update/'), {'name':'Renamed', 'network':'default', 'revision':self.workspace.updated_at.isoformat()}, content_type='application/json')
        assert response.status_code == 200
        self.workspace.refresh_from_db()
        assert self.workspace.name == 'Renamed'
        assert binding == (self.workspace.number, self.workspace.runtime_id, self.workspace.launch_request_id, self.workspace.endpoint_revision)

    def test_validation_duplicate_and_stale_edits(self):
        create_workspace(owner=self.user, name='Existing')
        for name, network, revision in [('Existing','default',self.workspace.updated_at.isoformat()), ('x'*256,'default',self.workspace.updated_at.isoformat()), ('Desk','other',self.workspace.updated_at.isoformat()), ('Desk','default','stale')]:
            response = self.client.post(self.url('update/'), {'name':name,'network':network,'revision':revision}, content_type='application/json')
            assert response.status_code == 409
        self.workspace.refresh_from_db()
        assert self.workspace.name == 'Desk' and self.workspace.network == 'default'

    def test_other_user_cannot_read_edit_delete_and_no_controller_called(self):
        self.client.force_login(self.other)
        with patch('zog.station_access.api.views.get_gateway', side_effect=AssertionError('authorize first')):
            assert self.client.get(self.url()).status_code == 404
            assert self.client.post(self.url('update/'), {}, content_type='application/json').status_code == 404
            assert self.client.post(self.url('delete/'), {}, content_type='application/json').status_code == 404

    def test_csrf_required_and_confirmation_required(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.user)
        assert client.post(self.url('delete/'), {}, content_type='application/json').status_code == 403
        assert self.client.post(self.url('delete/'), {}, content_type='application/json').status_code == 400

    def test_delete_dormant_requires_controller_and_never_reuses_number(self):
        number = self.workspace.number
        with self.assertRaises(WorkspaceOperationError):
            delete_workspace(self.workspace, None, revision=self.workspace.updated_at.isoformat())
        self.workspace.refresh_from_db()
        delete_workspace(self.workspace, self.gateway, revision=self.workspace.updated_at.isoformat())
        replacement = create_workspace(owner=self.user, name='Next')
        assert replacement.number > number and not replacement.desired_running

    def test_deleting_default_does_not_recreate_it(self):
        initial = VncWorkspace.objects.get(number=1)
        delete_workspace(initial, self.gateway, revision=initial.updated_at.isoformat())
        get_user_model().objects.create_superuser('administrator')
        assert not VncWorkspace.objects.filter(number=1).exists()

    def test_successful_delete_stops_runtime_and_removes_grants(self):
        from zog.station_access.services.workspaces import ensure_workspace_ready
        from zog.station_access.services.vnc import issue_vnc_grant
        ensure_workspace_ready(self.workspace, self.gateway)
        issue_vnc_grant(self.user, self.workspace, self.gateway)
        identifier, runtime = self.workspace.pk, self.workspace.runtime_id
        with patch('zog.station_access.api.views.get_gateway', return_value=self.gateway):
            response = self.client.post(self.url('delete/'), {'confirmed_workspace_id':str(identifier),'revision':self.workspace.updated_at.isoformat()}, content_type='application/json')
        assert response.status_code == 200
        assert not VncWorkspace.objects.filter(pk=identifier).exists()
        assert self.gateway.get_runtime(runtime).terminal

    def test_unconfirmed_stop_preserves_workspace_and_error(self):
        runtime = start_workspace(self.workspace, self.gateway)
        with patch.object(self.gateway, 'terminate_application_runtime', return_value=runtime):
            with self.assertRaises(WorkspaceOperationError):
                delete_workspace(self.workspace, self.gateway, revision=self.workspace.updated_at.isoformat())
        self.workspace.refresh_from_db()
        assert self.workspace.last_error and not self.workspace.desired_running

    def test_attached_application_blocks_before_desktop_stop(self):
        runtime = start_workspace(self.workspace, self.gateway)
        attached = self.gateway.launch_application('editor', request_id='editor-1', parameters={'workspace-number':self.workspace.number})
        with self.assertRaisesRegex(WorkspaceOperationError, attached.runtime_id):
            delete_workspace(self.workspace, self.gateway, revision=self.workspace.updated_at.isoformat())
        assert not self.gateway.get_runtime(runtime.runtime_id).terminal

    def test_missing_controller_and_stale_delete_preserve_workspace(self):
        start_workspace(self.workspace, self.gateway)
        with self.assertRaises(WorkspaceOperationError):
            delete_workspace(self.workspace, None, revision=self.workspace.updated_at.isoformat())
        with self.assertRaises(WorkspaceOperationError):
            delete_workspace(self.workspace, self.gateway, revision='stale')
        assert VncWorkspace.objects.filter(pk=self.workspace.pk).exists()

    def test_lost_reply_deletion_recovers_desktop_before_dependency_check(self):
        start_workspace(self.workspace, self.gateway)
        runtime_id = self.workspace.runtime_id
        self.workspace.runtime_id = None
        self.workspace.launch_pending = True
        self.workspace.save()
        delete_workspace(self.workspace, self.gateway, revision=self.workspace.updated_at.isoformat())
        assert self.gateway.get_runtime(runtime_id).terminal
