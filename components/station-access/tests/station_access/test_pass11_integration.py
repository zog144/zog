from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tempfile
import pytest
from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from zog.station_access.box_control.current import CurrentBoxControlGateway
from zog.station_access.box_control.journal import JournalReader, project_page
from zog.station_access.box_control.logs import LogsUnavailable, LogCursorExpired
from zog.station_access.models import VncWorkspace


class Pass11Tests(SimpleTestCase):
    def make_control(self):
        from zog.box_control.api import BoxControl
        from zog.box_control.project import Project
        from zog.box_control.model import ApplicationRuntimeState
        from zog.box_control.runtime.reference import ApplicationRuntimeReference, ProgramRuntimeReference, RuntimeReferenceStore
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        project = Project(Path(self.directory.name))
        reference = ApplicationRuntimeReference('runtime-one', 'worker', 'worker-one', 'generation-1', ApplicationRuntimeState.RUNNING,
            boot_id='a'*32, programs=(ProgramRuntimeReference('worker', 'worker.service', invocation_id='b'*32),))
        RuntimeReferenceStore(project.runtime_reference_file).save({'runtime-one': reference})
        # Real public controller API and real root-control journal cursor implementation.
        from root_control.journal import read_logs
        transport = SimpleNamespace(application_logs=lambda **kwargs: read_logs(**kwargs))
        return BoxControl(project, systemd_transport=transport), reference

    def test_real_controller_log_api_projects_and_preserves_cursor(self):
        control, reference = self.make_control()
        from root_control import journal
        row = {'__CURSOR': 'journal-position-1', '__REALTIME_TIMESTAMP': '1750000000000000',
            '_BOOT_ID': 'a'*32, '_SYSTEMD_INVOCATION_ID': 'b'*32, 'PRIORITY': '3', 'MESSAGE': 'failure\ntraceback'}
        reader = JournalReader(control)
        with patch.object(journal, 'run_bounded', return_value=[row]) as read:
            first = reader.read_logs('runtime-one', program='worker', limit=50)
            assert first.entries[0].message == 'failure\ntraceback'
            assert first.entries[0].priority == 3
            assert first.entries[0].invocation_id == 'b'*32
            assert first.next_cursor
            assert '_SYSTEMD_INVOCATION_ID='+'b'*32 in read.call_args.args[0]
            second = reader.read_logs('runtime-one', program='worker', cursor=first.next_cursor, limit=50)
            assert not second.entries and second.next_cursor == first.next_cursor
        with patch.object(journal, 'run_bounded', return_value=[]):
            with pytest.raises(LogCursorExpired):
                reader.read_logs('runtime-one', program='worker', cursor=first.next_cursor)

    def test_empty_missing_identity_and_unavailable_are_distinct(self):
        assert project_page({'status':'empty-history','entries':[], 'next_cursor':None},program='p',invocation_id='i',cursor=None,scope='s').status == 'empty-history'
        for status in ['identity-unavailable', 'unavailable']:
            with pytest.raises(LogsUnavailable):
                project_page({'status':status},program='p',invocation_id='i',cursor='keep',scope='s')

    def test_identical_messages_remain_distinct_and_missing_message_is_visible(self):
        page = project_page({'status':'ok','entries':[{'message':'same'}, {'message':'same'}, {'message':None,'message_unavailable':True}], 'next_cursor':'next'},
            program='worker',invocation_id='i',cursor=None,scope='s')
        assert len({entry.cursor for entry in page.entries}) == 3
        assert 'Message unavailable' in page.entries[2].message

    def test_fresh_observation_uses_pass11_shape_and_fails_closed(self):
        from zog.station_access.box_control.port import BoxControlUnavailable
        control, reference = self.make_control()
        gateway = CurrentBoxControlGateway.__new__(CurrentBoxControlGateway)
        gateway._control = control
        with patch.object(control, 'observe_application_runtime', return_value={'status':'observed', 'programs':[{'status':'absent','observation':None}]}):
            assert gateway.get_current_runtime('runtime-one').terminal
        with patch.object(control, 'observe_application_runtime', return_value={'status':'partial', 'programs':[]}):
            with pytest.raises(BoxControlUnavailable):
                gateway.get_current_runtime('runtime-one')
        with patch.object(control, 'observe_application_runtime', side_effect=AssertionError('no observation during log authorization')):
            assert gateway.get_runtime('runtime-one').runtime_id == 'runtime-one'


class BootstrapTests(TestCase):
    def test_initial_admin_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STATE_DIRECTORY=Path(directory)):
            call_command('initialize_station', verbosity=0)
            user = get_user_model().objects.get(username='station-admin')
            text = (Path(directory)/'FIRST-LOGIN.txt').read_text()
            password = next(line.removeprefix('Password: ') for line in text.splitlines() if line.startswith('Password: '))
            assert len(password) >= 40 and user.check_password(password)
            assert password not in user.password
            assert self.client.login(username='station-admin', password=password)
            assert VncWorkspace.objects.get(number=1).owner_id == user.pk
            hashed = user.password
            call_command('initialize_station', verbosity=0)
            user.refresh_from_db()
            assert user.password == hashed

    def test_existing_ordinary_account_is_not_elevated(self):
        user = get_user_model().objects.create_user('station-admin', password='existing')
        call_command('initialize_station', verbosity=0)
        user.refresh_from_db()
        assert not user.is_superuser and user.check_password('existing')

    def test_frontend_routes_and_asset_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'assets').mkdir()
            (root/'index.html').write_text('<div id="root">portal</div>')
            (root/'assets'/'application-0123456789ab.js').write_text('console.log("portal")')
            with override_settings(STATION_ACCESS_FRONTEND_DIRECTORY=root):
                for path in ['/', '/workspaces', '/runtimes/one', '/build-jobs/one']:
                    response = self.client.get(path)
                    assert response.status_code == 200
                    response.close()
                response = self.client.get('/assets/application-0123456789ab.js')
                assert response.status_code == 200
                response.close()
                assert self.client.get('/assets/../../state/FIRST-LOGIN.txt').status_code == 404
                assert self.client.get('/state/FIRST-LOGIN.txt').status_code == 404
                assert self.client.get('/api/missing/').status_code == 404

    def test_build_access_is_admin_only_before_gateway_call(self):
        get_user_model().objects.create_user('reader', password='secret')
        self.client.login(username='reader', password='secret')
        with patch('zog.station_access.api.views.get_gateway', side_effect=AssertionError('must authorize first')):
            assert self.client.get('/api/build-jobs/').status_code == 404
            assert self.client.get('/api/build-jobs/job-1/logs/').status_code == 404

    def test_admin_build_pages_preserve_cursor_and_execution_scope(self):
        from zog.station_access.box_control.logs import LogPage, LogEntry
        get_user_model().objects.create_superuser('operator', password='test-only')
        self.client.login(username='operator', password='test-only')
        gateway = Mock()
        gateway.list_build_jobs.return_value = {'jobs':[{'job_id':'job-1','state':'running'}], 'next_after':'job-1','has_more':False}
        gateway.get_build_job.return_value = {'job_id':'job-1','state':'running','invocation_id':'invocation-1'}
        gateway.read_build_logs.return_value = LogPage((LogEntry('row-1','2026-09-19T00:00:00Z','build-command',6,'compiling','invocation-1'),),'cursor-next')
        with patch('zog.station_access.api.views.get_gateway', return_value=gateway):
            assert self.client.get('/api/build-jobs/').json()['jobs'][0]['job_id'] == 'job-1'
            assert self.client.get('/api/build-jobs/job-1/').json()['job']['state'] == 'running'
            response = self.client.get('/api/build-jobs/job-1/logs/', {'cursor':'cursor-old','limit':20})
            assert response.status_code == 200
            assert response.json()['next_cursor'] == 'cursor-next'
            assert response['Cache-Control'] == 'no-store'
            gateway.read_build_logs.assert_called_once_with('job-1',cursor='cursor-old',limit=20)
            gateway.read_build_logs.return_value = LogPage((LogEntry('wrong','now','build-command',6,'wrong invocation','another'),),None)
            assert self.client.get('/api/build-jobs/job-1/logs/').status_code == 503

    def test_build_reader_passes_through_job_and_cursor(self):
        control = Mock()
        control.inspect_build_job.return_value = {'boot_id':'boot','invocation_id':'invocation'}
        control.build_job_logs.return_value = {'status':'ok','entries':[{'priority':'6','message':'building'}], 'next_cursor':'next','has_more':False}
        page = JournalReader(control).read_build_logs('job-1',cursor='old',limit=15)
        control.build_job_logs.assert_called_once_with('job-1',cursor='old',limit=15)
        assert page.entries[0].invocation_id == 'invocation'
        assert page.entries[0].program == 'build-command'
