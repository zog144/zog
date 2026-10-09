import copy
import json
import time
import uuid
from datetime import timedelta
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import signatures
from zog.station_access.host_registry.models import Host, HostIdentity, MirrorRole
from zog.station_access.host_registry import identity
from zog.station_access.archive_inventory.models import Observation, Entry
from zog.station_access.archive_inventory.views import persist
from zog.station_access.archive_inventory.contract import validate

ORIGIN = 'https://registry.example.test'


@override_settings(HOST_IDENTITY_ORIGIN=ORIGIN, ALLOWED_HOSTS=['registry.example.test', 'testserver'])
class InventoryTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('admin', password='fixture')
        self.host = Host.objects.create(label='Mirror A', signed_last_received=timezone.now())
        self.key = Ed25519PrivateKey.generate()
        HostIdentity.objects.create(host=self.host, fingerprint=signatures.fingerprint(self.key.public_key()), public_key=signatures.public_text(self.key.public_key()), approved_by='fixture', approved_at=timezone.now())
        self.role = MirrorRole.objects.create(host=self.host, selected=True, endpoint='https://mirror.example.test', revision=1, changed_at=timezone.now())
        self.client.force_login(self.admin)

    def item(self, index=0, **changes):
        return dict(collection='sources', digest=f'{index:064x}', kind='source', name='Source', version='abcdef0', size_bytes=1000000,
            availability='present', filesystem_id='1', provenance='source-export', approval='unknown') | changes

    def report(self, rows=None, **changes):
        rows = [self.item()] if rows is None else rows
        return dict(version=1, host_id=str(self.host.id), role_revision=1, observation_id=str(uuid.uuid4()), observed_at=timezone.now().isoformat(),
            preparation=dict(state='unknown',attempt_id=None), status='ok', serving=True, lease_expires_at=int(time.time())+800, total=len(rows), offset=0, items=rows,
            summary=dict(collections=['sources','root-filesystems'],logical_bytes=0,unique_content_bytes=0,allocated_object_bytes=4096,accounting_complete=True,
                filesystems=[dict(id='1',stores=['store','objects'],total_bytes=100000000,used_bytes=5000000,available_bytes=90000000,allocated_object_bytes=4096)])) | changes

    def save(self, data):
        with identity.locked():
            return persist(self.host, data, validate(data))

    def send(self, value, key=None, message=None):
        message = message or signatures.sign(ORIGIN+f'/api/archives/reports/{self.host.id}/', json.dumps(value).encode(), key or self.key, str(self.host.id))
        headers = {'HTTP_'+k.upper().replace('-','_'):v for k,v in message.headers.items() if k.lower() not in ['content-type','content-length']}
        return self.client.post(message.path_url, message.body, content_type='application/json', HTTP_HOST='registry.example.test', **headers)

    def mirror(self):
        return self.client.get('/api/archives/mirrors/').json()['mirrors'][0]

    def test_admin_boundaries_and_read_only(self):
        for path in ['/archives/','/api/archives/mirrors/','/api/archives/items/']:
            self.client.logout(); self.assertEqual(self.client.get(path).status_code,401)
            user=get_user_model().objects.create_user('user'+str(uuid.uuid4()))
            self.client.force_login(user); self.assertEqual(self.client.get(path).status_code,403)
            self.client.force_login(self.admin)
        self.assertEqual(self.client.post('/api/archives/mirrors/').status_code,405)
        self.assertIn('no-store',self.client.get('/api/archives/mirrors/')['Cache-Control'])

    def test_real_signed_ingestion_replay_and_key_binding(self):
        value=self.report()
        self.assertEqual(self.send(value, key=Ed25519PrivateKey.generate()).status_code,401)
        message=signatures.sign(ORIGIN+f'/api/archives/reports/{self.host.id}/',json.dumps(value).encode(),self.key,str(self.host.id))
        self.assertEqual(self.send(value,message=message).status_code,200)
        self.assertEqual(self.send(value,message=message).status_code,400)
        HostIdentity.objects.update(status='revoked')
        self.assertEqual(self.send(self.report()).status_code,401)

    def test_atomic_pages_filter_and_dedup_accounting(self):
        rows=[self.item(i) for i in range(101)]
        rows.append(self.item(0,collection='root-filesystems',kind='root-filesystem',approval='unapproved'))
        value=self.report(rows[:100],total=102)
        self.assertFalse(self.save(value));self.assertIsNone(self.mirror()['snapshot'])
        second=dict(value,offset=100,items=rows[100:])
        self.assertTrue(self.save(second))
        mirror=self.mirror()
        self.assertEqual(mirror['state'],'serving')
        self.assertEqual(mirror['summary']['logical_bytes'],102000000)
        self.assertEqual(mirror['summary']['unique_content_bytes'],101000000)
        base=f"/api/archives/items/?mirror={self.host.id}&snapshot={mirror['snapshot']}&limit=100"
        first=self.client.get(base).json();self.assertEqual(len(first['items']),100)
        next_page=self.client.get(base+'&after='+str(first['next_cursor'])).json()
        self.assertEqual(len(next_page['items']),2);self.assertIsNone(next_page['next_cursor'])
        root=self.client.get(base+'&collection=root-filesystems').json()
        self.assertEqual(root['items'][0]['kind'],'root-filesystem');self.assertEqual(root['items'][0]['approval'],'unapproved')

    def test_missing_sizes_are_unknown(self):
        value=self.report([self.item(size_bytes=None)])
        value['summary']['allocated_object_bytes']=None
        self.save(value);summary=self.mirror()['summary']
        self.assertIsNone(summary['logical_bytes']);self.assertIsNone(summary['unique_content_bytes']);self.assertIsNone(summary['allocated_object_bytes'])

    def test_empty_unavailable_stale_and_retention(self):
        self.assertEqual(self.mirror()['observation_state'],'unavailable');self.assertIsNone(self.mirror()['archive_count'])
        value=self.report([]);self.save(value)
        self.assertEqual(self.mirror()['archive_count'],0);self.assertEqual(self.mirror()['observation_state'],'observed')
        self.save(self.report([],status='unavailable',serving=False,lease_expires_at=None))
        self.assertEqual(self.mirror()['observation_state'],'unavailable');self.assertEqual(self.mirror()['snapshot'],value['observation_id'])
        Observation.objects.update(observed_at=timezone.now()-timedelta(minutes=10))
        self.assertEqual(self.mirror()['observation_state'],'stale')
        self.role.selected=False;self.role.revision=2;self.role.save()
        self.assertEqual(self.mirror()['state'],'not-selected');self.assertIsNotNone(self.mirror()['snapshot'])

    def test_role_evidence_does_not_invent_readiness(self):
        self.assertEqual(self.mirror()['state'],'assigned')
        self.role.reported_state='starting';self.role.acknowledged_revision=1;self.role.observed_at=timezone.now();self.role.save()
        self.assertEqual(self.mirror()['state'],'starting')
        self.role.reported_state='blocked';self.role.reason='bridge-unconfigured';self.role.save()
        self.assertEqual(self.mirror()['state'],'blocked')
        self.role.reported_state='ready';self.role.save()
        self.assertNotEqual(self.mirror()['state'],'serving')

    def test_bounds_redaction_and_invalid_reports(self):
        for update in [dict(role_revision=2),dict(total=10001),dict(items=[self.item()]*101,total=101),dict(observed_at=(timezone.now()-timedelta(hours=1)).isoformat())]:
            self.assertEqual(self.send(self.report(**update)).status_code,400)
        for update in [dict(token='private-secret'),dict(name='https://user:private-secret@example.test'),dict(provenance={'token':'private-secret'})]:
            value=self.report();value['items'][0].update(update)
            result=self.send(value);self.assertEqual(result.status_code,400);self.assertNotIn('private-secret',result.content.decode())
        self.assertEqual(self.client.post(f'/api/archives/reports/{self.host.id}/',b'x'*256001,content_type='application/json').status_code,413)
        for query in ['limit=0','limit=101','limit=wat','after=bad','limit=2&limit=3','url=https://evil.test']:
            self.assertEqual(self.client.get('/api/archives/mirrors/?'+query).status_code,400)

    def test_snapshot_consistency_and_storage_bound(self):
        original=self.report();self.save(original)
        partial=self.report(total=2);self.save(partial)
        broken=dict(partial,offset=1,items=[self.item(1)]);broken['summary']=dict(partial['summary'],logical_bytes=123)
        with self.assertRaises(ValueError):self.save(broken)
        self.assertEqual(self.mirror()['snapshot'],original['observation_id'])
        self.save(self.report())
        self.assertEqual(Observation.objects.count(),1)
        self.assertEqual(self.client.get(f'/api/archives/items/?mirror={self.host.id}&snapshot={original["observation_id"]}').status_code,409)

    def test_mirror_keyset_pagination(self):
        for index in range(4):
            host=Host.objects.create(label=str(index));MirrorRole.objects.create(host=host,changed_at=timezone.now())
        seen=[];after=''
        while True:
            data=self.client.get('/api/archives/mirrors/?limit=2'+('&after='+after if after else '')).json()
            seen.extend(row['host_id'] for row in data['mirrors']);after=data['next_cursor']
            if after is None:break
        self.assertEqual(len(seen),5);self.assertEqual(len(set(seen)),5)

    def test_preparation_requires_controller_evidence(self):
        self.save(self.report([], status='unavailable', serving=False, lease_expires_at=None,
            preparation=dict(state='preparing', attempt_id='a'*32)))
        self.assertEqual(self.mirror()['state'], 'preparing')
        self.assertTrue(self.mirror()['preparation']['fresh'])
        self.save(self.report([], status='unavailable', serving=False, lease_expires_at=None,
            preparation=dict(state='uncertain', attempt_id='b'*32)))
        self.assertEqual(self.mirror()['state'], 'blocked')
        Observation.objects.update(observed_at=timezone.now()-timedelta(minutes=10))
        self.assertNotEqual(self.mirror()['state'], 'preparing')

    def test_preparation_inspection_is_read_only(self):
        from unittest.mock import patch, MagicMock
        from zog.station_access.archive_inventory.management.commands.report_archive_inventory import preparation
        import sys
        controller = MagicMock()
        controller.application_preparation.return_value = dict(state='preparing',attempt_id='c'*32)
        api = MagicMock();api.BoxControl.return_value=controller
        with patch.dict(sys.modules, {'zog.box_control.api':api,'zog.box_control.project':MagicMock()}):
            result=preparation(dict(controller_project='/fixture-project',application='station-access'))
        self.assertEqual(result['state'],'preparing')
        self.assertEqual([call[0] for call in controller.mock_calls], ['application_preparation'])
        self.assertEqual(preparation({})['state'],'unknown')

    def notice_fixture(self):
        from zog.archive_mirror import notice_contract as c
        text='<script>alert("fixture")</script>\nExact upstream terms\n'
        sha=c.digest(text.encode());row=self.item()
        value=dict(schema=1,collection=row['collection'],archive_digest=row['digest'],artifact_kind='source',
            source_identity=dict(kind='release-archive',digest=row['digest'],revision=None),generation=None,
            records=[dict(package='example',version='1.0',revision=None,stage=None,source_digest=row['digest'],origin='https://example.org/source',expression='MIT',
                review='declared',scope='package',exceptions=[],issues=[],texts=[sha],receipt_digest=None)],texts={sha:text},coverage='recorded',source_material='unknown')
        row['licenses']=c.summary(value)
        return value,self.report([row],version=2)

    def upload_notice(self,value,key=None,message=None):
        from zog.archive_mirror import notice_contract as c
        url=ORIGIN+f'/api/archives/reports/{self.host.id}/notices/'
        message=message or signatures.sign(url,c.canonical(value),key or self.key,str(self.host.id))
        return self.send(value,message=message)

    def notice_query(self,report,**kw):
        from urllib.parse import urlencode
        row=report['items'][0]
        return '/api/archives/notices/?'+urlencode(dict(mirror=str(self.host.id),snapshot=report['observation_id'],collection=row['collection'],digest=row['digest'],**kw))

    def test_notice_v2_signed_upload_admin_read_download_and_redaction(self):
        value,report=self.notice_fixture()
        response=self.send(report);self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['missing_notices']),1)
        self.assertEqual(self.client.get(self.notice_query(report)).status_code,404)
        self.assertEqual(self.upload_notice(value,key=Ed25519PrivateKey.generate()).status_code,401)
        self.assertEqual(self.upload_notice(value).status_code,200)
        self.assertEqual(self.upload_notice(value).status_code,200)
        detail=self.client.get(self.notice_query(report));self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.json()['records'][0]['version'],'1.0')
        self.assertNotIn('texts": {',detail.content.decode())
        result=self.client.get(self.notice_query(report,format='text'))
        self.assertEqual(result.status_code,200);self.assertIn('text/plain',result['Content-Type']);self.assertIn('nosniff',result['X-Content-Type-Options'])
        self.assertIn(b'<script>',result.content);self.assertIn('sandbox',result['Content-Security-Policy'])
        self.client.logout();self.assertEqual(self.client.get(self.notice_query(report)).status_code,401)
        user=get_user_model().objects.create_user('ordinary');self.client.force_login(user)
        self.assertEqual(self.client.get(self.notice_query(report,format='text')).status_code,403)
        HostIdentity.objects.update(status='revoked');self.assertEqual(self.upload_notice(value).status_code,401)

    def test_notice_missing_old_v1_and_strict_v2(self):
        from zog.archive_mirror import notice_contract as c
        old=self.report();self.save(old)
        self.assertEqual(self.client.get(self.notice_query(old)).status_code,404)
        value,report=self.notice_fixture()
        wrong=copy.deepcopy(report);wrong['version']=1
        with self.assertRaises(ValueError):validate(wrong)
        wrong=copy.deepcopy(report);wrong['items'][0]['licenses']['url']='https://private-secret@evil.test'
        with self.assertRaises(ValueError):validate(wrong)
        wrong=copy.deepcopy(report);wrong['items'][0]['licenses']['notice_bytes']=c.MAX_DOCUMENT+1
        with self.assertRaises(ValueError):validate(wrong)
        self.assertEqual(self.upload_notice(value).status_code,400)
        self.assertEqual(self.client.post(f'/api/archives/reports/{self.host.id}/notices/',b' '*(c.MAX_BUNDLE+1),content_type='application/json').status_code,413)

    def test_notice_conflict_replay_scope_pagination_and_forged_urls(self):
        from zog.archive_mirror import notice_contract as c
        value,report=self.notice_fixture()
        value['records'].append(dict(value['records'][0],package='other',expression='BSD-2-Clause'))
        report['items'][0]['licenses']=c.summary(value);self.save(report)
        message=signatures.sign(ORIGIN+f'/api/archives/reports/{self.host.id}/notices/',c.canonical(value),self.key,str(self.host.id))
        self.assertEqual(self.upload_notice(value,message=message).status_code,200)
        self.assertEqual(self.upload_notice(value,message=message).status_code,400)
        page=self.client.get(self.notice_query(report,limit=1)).json();self.assertEqual(page['next_offset'],1)
        self.assertEqual(self.client.get(self.notice_query(report,limit=1,offset=1)).json()['records'][0]['package'],'other')
        self.assertEqual(self.client.get(self.notice_query(report,limit=26)).status_code,400)
        self.assertEqual(self.client.get(self.notice_query(report)+'&url=https://evil.test').status_code,400)
        self.assertEqual(self.client.get(self.notice_query(report).replace('collection=sources','collection=other')).status_code,409)
        changed=copy.deepcopy(value);changed['records'][0]['version']='2.0'
        report['observation_id']=str(uuid.uuid4());report['observed_at']=timezone.now().isoformat();report['items'][0]['licenses']=c.summary(changed);self.save(report)
        self.assertEqual(self.upload_notice(changed).status_code,409)
        self.assertEqual(self.client.get(self.notice_query(report)).status_code,404)

    def test_notice_hash_corruption_cache_capacity_and_role_revision(self):
        from zog.archive_mirror import notice_contract as c
        from unittest.mock import patch
        value,report=self.notice_fixture();self.save(report)
        broken=copy.deepcopy(value);broken['texts'][next(iter(broken['texts']))]='changed'
        self.assertEqual(self.upload_notice(broken).status_code,400)
        with patch('zog.station_access.archive_inventory.notice_views.MAX_HOST_BYTES',1):
            self.assertEqual(self.upload_notice(value).status_code,413)
        MirrorRole.objects.update(revision=2);self.assertEqual(self.upload_notice(value).status_code,400)

    def test_notice_mixed_version_continuation_and_stale_upload_rejected(self):
        value, report = self.notice_fixture()
        first = dict(report, total=2)
        self.assertFalse(self.save(first))
        mixed = dict(first, version=1, offset=1, items=[self.item(1)])
        with self.assertRaises(ValueError): self.save(mixed)
        Observation.objects.update(observed_at=timezone.now()-timedelta(minutes=10))
        self.assertEqual(self.upload_notice(value).status_code,400)


    def generation_fixture(self, *, expression='MIT', review='reviewed', origin='https://example.org/source', source_digest=None, issues=None):
        from zog.archive_mirror import notice_contract as c
        generation = 'generation-1'
        digest = 'e' * 64
        source_digest = source_digest if source_digest is not None else 'f' * 64
        notice_text = 'Example license notice\n'
        notice_sha = c.digest(notice_text.encode())
        value = dict(
            schema=1, collection='root-filesystems', archive_digest=digest,
            artifact_kind='root-filesystem',
            source_identity=dict(kind='root-filesystem', digest=digest, revision=None),
            generation=generation,
            records=[dict(
                package='example', version='1.0', revision=None, stage='final',
                source_digest=source_digest, origin=origin, expression=expression,
                review=review, scope='package', exceptions=[], issues=issues or [],
                texts=[notice_sha], receipt_digest=None,
            )],
            texts={notice_sha: notice_text}, coverage='recorded', source_material='verified',
        )
        summary = c.summary(value)
        item = self.item(
            collection='root-filesystems', digest=digest, kind='root-filesystem',
            name='Zog rootfs', version=generation, provenance='source-export',
            approval='approved', licenses=summary,
        )
        report = self.report([item], version=2)
        self.save(report)
        from zog.station_access.archive_inventory.models import NoticeBundle
        NoticeBundle.objects.create(
            host=self.host, collection=item['collection'], digest=digest,
            bundle_digest=summary['bundle_digest'], size=len(c.canonical(value)), evidence=value,
        )
        return generation, report, value

    def generation_url(self, generation, report):
        from urllib.parse import urlencode
        item = report['items'][0]
        return '/api/archives/generations/' + generation + '/?' + urlencode(dict(
            mirror=str(self.host.id), snapshot=report['observation_id'],
            collection=item['collection'], digest=item['digest'],
        ))

    def test_generation_detail_computes_complete_coverage_from_bound_evidence(self):
        generation, report, _ = self.generation_fixture()
        result = self.client.get(self.generation_url(generation, report))
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body['generation'], generation)
        self.assertEqual(body['coverage']['source_provenance'], dict(state='complete', complete=1, total=1))
        self.assertEqual(body['coverage']['license_evidence'], dict(state='complete', complete=1, total=1))
        self.assertEqual(body['coverage']['unresolved_provenance'], 0)
        self.assertEqual(body['patches']['state'], 'not-integrated')
        self.assertEqual(body['packages'][0]['patches'], {'state': 'not-integrated', 'count': None, 'items': []})
        self.assertEqual(body['build_evidence']['state'], 'not-integrated')

    def test_generation_detail_never_promotes_incomplete_evidence(self):
        generation, report, _ = self.generation_fixture(expression=None, review='unresolved', origin=None, source_digest=None, issues=['missing review'])
        body = self.client.get(self.generation_url(generation, report)).json()
        self.assertEqual(body['coverage']['source_provenance'], dict(state='incomplete', complete=0, total=1))
        self.assertEqual(body['coverage']['license_evidence'], dict(state='incomplete', complete=0, total=1))
        self.assertEqual(body['coverage']['unresolved_provenance'], 1)

    def test_generation_detail_missing_bundle_is_unknown_not_zero(self):
        generation, report, _ = self.generation_fixture()
        from zog.station_access.archive_inventory.models import NoticeBundle
        NoticeBundle.objects.all().delete()
        body = self.client.get(self.generation_url(generation, report)).json()
        self.assertEqual(body['evidence_state'], 'missing')
        self.assertEqual(body['coverage']['source_provenance']['state'], 'unknown')
        self.assertIsNone(body['coverage']['source_provenance']['total'])
        self.assertIsNone(body['coverage']['unresolved_provenance'])

    def test_generation_detail_rejects_wrong_generation_and_non_admin(self):
        generation, report, _ = self.generation_fixture()
        self.assertEqual(self.client.get(self.generation_url('other-generation', report)).status_code, 400)
        self.client.logout()
        user = get_user_model().objects.create_user('generation-user')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.generation_url(generation, report)).status_code, 403)


    def generation_export_url(self, generation, report):
        return self.generation_url(generation, report).replace(
            '/api/archives/generations/' + generation + '/',
            '/api/archives/generations/' + generation + '/export/',
        )

    def test_generation_export_is_versioned_bound_and_matches_detail(self):
        generation, report, _ = self.generation_fixture()
        detail = self.client.get(self.generation_url(generation, report)).json()
        result = self.client.get(self.generation_export_url(generation, report))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result['Cache-Control'], 'no-store')
        self.assertEqual(result['X-Content-Type-Options'], 'nosniff')
        self.assertIn('application/json', result['Content-Type'])
        self.assertEqual(
            result['Content-Disposition'],
            'attachment; filename="generation-generation-1.provenance.v1.json"',
        )
        exported = json.loads(result.content)
        self.assertEqual(exported['schema'], 1)
        self.assertEqual(exported['kind'], 'zog-generation-provenance')
        self.assertEqual(exported['generation'], {
            'identity': detail['generation'],
            'rootfs_sha256': detail['archive']['digest'],
        })
        self.assertEqual(exported['archive']['mirror'], detail['archive']['mirror'])
        self.assertEqual(exported['archive']['snapshot'], detail['archive']['snapshot'])
        self.assertEqual(exported['evidence']['coverage'], detail['coverage'])
        self.assertEqual(exported['packages'][0]['package'], detail['packages'][0]['package'])
        self.assertEqual(exported['patches']['state'], 'not-integrated')
        self.assertEqual(exported['build_evidence']['state'], 'not-integrated')
        self.assertTrue(result.content.endswith(b'\n'))

    def test_generation_export_preserves_unknown_evidence_and_permissions(self):
        generation, report, _ = self.generation_fixture()
        from zog.station_access.archive_inventory.models import NoticeBundle
        NoticeBundle.objects.all().delete()
        exported = json.loads(self.client.get(self.generation_export_url(generation, report)).content)
        self.assertEqual(exported['evidence']['state'], 'missing')
        self.assertEqual(exported['evidence']['coverage']['source_provenance']['state'], 'unknown')
        self.assertIsNone(exported['evidence']['coverage']['unresolved_provenance'])
        self.assertEqual(exported['packages'], [])

        self.assertEqual(
            self.client.get(self.generation_export_url('other-generation', report)).status_code,
            400,
        )
        self.client.logout()
        self.client.force_login(get_user_model().objects.create_user('export-user'))
        self.assertEqual(
            self.client.get(self.generation_export_url(generation, report)).status_code,
            403,
        )

    def test_export_projection_is_deterministic_for_unordered_package_fields(self):
        from zog.station_access.archive_inventory.generation_views import export_payload
        generation, report, _ = self.generation_fixture()
        payload = self.client.get(self.generation_url(generation, report)).json()
        first = copy.deepcopy(payload['packages'][0])
        first.update(package='zeta', issues=['z', 'a'], exceptions=[
            {'scope':'two','expression':'MIT','review':'reviewed','notes':None},
            {'scope':'one','expression':'BSD-2-Clause','review':'declared','notes':'note'},
        ])
        second = copy.deepcopy(payload['packages'][0])
        second.update(package='alpha', issues=['b', 'a'])
        payload['packages'] = [first, second]
        projected = export_payload(payload)
        self.assertEqual([row['package'] for row in projected['packages']], ['alpha', 'zeta'])
        self.assertEqual(projected['packages'][0]['issues'], ['a', 'b'])
        self.assertEqual(
            [part['scope'] for part in projected['packages'][1]['exceptions']],
            ['one', 'two'],
        )
