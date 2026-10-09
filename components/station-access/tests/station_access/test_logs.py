from dataclasses import replace
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from zog.station_access.box_control.fixture import _GATEWAY
from zog.station_access.box_control.logs import LogPage, LogEntry, LogsUnavailable
from zog.station_access.models import ApplicationOwnership

@override_settings(STATION_ACCESS_BOX_CONTROL_GATEWAY_FACTORY='zog.station_access.box_control.fixture:create_gateway')
class LogTests(TestCase):
    def setUp(self):
        _GATEWAY.runtimes.clear(); _GATEWAY.parameters.clear(); _GATEWAY.cancelled.clear()
        self.owner = get_user_model().objects.create_user('log-owner')
        self.other = get_user_model().objects.create_user('log-other')
        ApplicationOwnership.objects.create(application_name='browser', owner=self.owner)
        self.runtime = _GATEWAY.launch_application('browser', request_id='log-test')
        self.path = f'/api/runtimes/{self.runtime.runtime_id}/logs/'
        self.client.force_login(self.owner)

    def test_scope_auth_and_bounds(self):
        self.client.logout()
        assert self.client.get(self.path).status_code == 401
        self.client.force_login(self.other)
        assert self.client.get(self.path).status_code == 404
        self.client.force_login(self.owner)
        assert self.client.get(self.path, {'program': 'foreign-service'}).status_code == 404
        for query in ({'limit': 201}, {'limit': 'x'}, {'limit': 0}, {'cursor': 'x'*4097}):
            assert self.client.get(self.path, query).status_code == 400

    def test_cursor_pagination_is_bounded_and_nonduplicating(self):
        first = self.client.get(self.path, {'limit': 2}).json()
        assert first['source'] == 'fixture' and len(first['entries']) == 2 and first['has_more']
        second = self.client.get(self.path, {'limit': 2, 'cursor': first['next_cursor']}).json()
        assert not {e['cursor'] for e in first['entries']} & {e['cursor'] for e in second['entries']}
        invalid = self.client.get(self.path, {'cursor': 'foreign:2'})
        assert invalid.status_code == 410
        response = self.client.get(self.path)
        assert response['Cache-Control'] == 'no-store'
        assert '\nTraceback' in response.json()['entries'][4]['message']

    def test_no_live_adapter_is_an_explicit_unavailable_response(self):
        with patch.object(_GATEWAY, 'read_logs', side_effect=LogsUnavailable('Waiting for controller adapter')):
            response = self.client.get(self.path)
        assert response.status_code == 503
        assert response.json()['error'] == 'logs_unavailable'

    def test_wrong_invocation_is_never_exposed(self):
        runtime = replace(self.runtime, programs=(replace(self.runtime.programs[0], invocation_id='correct'),))
        _GATEWAY.runtimes[runtime.runtime_id] = runtime
        page = LogPage((LogEntry('c', '2026-09-16T00:00:00Z', 'vnc', 6, 'foreign log', 'wrong'),), 'c')
        with patch.object(_GATEWAY, 'read_logs', return_value=page):
            response = self.client.get(self.path)
        assert response.status_code == 503
        assert 'foreign log' not in response.content.decode()
