from django.test import TestCase
from django.utils import timezone

from zog.station_access.archive_inventory.models import Entry, Observation
from zog.station_access.host_registry.models import Host
from zog.station_access.host_registry.retirement import preview


def evidence(generation='generation-a'):
    return {
        'schema': 1,
        'source': 'verified-host-install-state-v1',
        'installation': {
            'installation_id': '00000001-0001-4001-8001-000000000001',
            'record_id': '00000005-0005-4005-8005-000000000005',
            'record_schema': 1,
            'operation': 'fresh',
        },
        'selected_slot': 'HOST-A',
        'booted_slot': None,
        'slots': {
            'HOST-A': {
                'generation': generation,
                'root_partuuid': '00000009-0009-4009-8009-000000000009',
            },
            'HOST-B': None,
        },
        'transitional_boot_bundle': {
            'kind': 'foreign',
            'provider': 'amazon-linux-2023',
            'record_reference': '00000007-0007-4007-8007-000000000007',
            'record_sha256': 'b' * 64,
        },
    }


class HostGenerationPreviewTests(TestCase):
    def setUp(self):
        self.host = Host.objects.create(
            label='Zog host',
            report={'version': 1, 'host_generation': evidence()},
            last_received=timezone.now(),
        )

    def archive(self, digest, generation='generation-a'):
        mirror = Host.objects.create(label='mirror-' + digest[:4])
        observation = Observation.objects.create(
            host=mirror,
            schema_version=2,
            role_revision=1,
            observed_at=timezone.now(),
            status='ok',
            serving=True,
            preparation={},
            summary={},
            total=1,
            complete=True,
        )
        Entry.objects.create(
            observation=observation,
            position=0,
            collection='root-filesystems',
            digest=digest,
            metadata={
                'kind': 'root-filesystem',
                'version': generation,
                'name': 'Zog rootfs',
                'size_bytes': 1,
                'availability': 'present',
                'provenance': 'source-export',
                'approval': 'approved',
            },
        )
        return mirror, observation

    def test_resolved_slot_uses_exact_archive_observation(self):
        mirror, observation = self.archive('a' * 64)
        value = preview(self.host)['host_generation']
        self.assertEqual(value['source'], 'verified-host-install-state-v1')
        self.assertEqual(value['selected_slot'], 'HOST-A')
        self.assertIsNone(value['booted_slot'])
        self.assertIsNone(value['slots']['HOST-B'])
        slot = value['slots']['HOST-A']
        self.assertEqual(slot['resolution'], 'resolved')
        self.assertEqual(slot['digest'], 'a' * 64)
        self.assertEqual(slot['archive'], {
            'mirror': str(mirror.pk),
            'snapshot': str(observation.pk),
            'collection': 'root-filesystems',
            'digest': 'a' * 64,
            'observed_at': observation.observed_at.isoformat(),
        })
        self.assertEqual(value['transitional_boot_bundle']['provider'], 'amazon-linux-2023')

    def test_conflicting_rootfs_digests_never_choose_one(self):
        self.archive('a' * 64)
        self.archive('c' * 64)
        slot = preview(self.host)['host_generation']['slots']['HOST-A']
        self.assertEqual(slot['resolution'], 'conflict')
        self.assertEqual(slot['candidate_count'], 2)
        self.assertIsNone(slot['digest'])
        self.assertIsNone(slot['archive'])

    def test_archive_resolution_does_not_change_removal_revision(self):
        before = preview(self.host)
        self.assertEqual(before['host_generation']['slots']['HOST-A']['resolution'], 'unresolved')
        original_revision = before['revision']
        self.archive('d' * 64)
        after = preview(self.host)
        self.assertEqual(after['revision'], original_revision)
        self.assertEqual(after['host_generation']['slots']['HOST-A']['resolution'], 'resolved')

    def test_booted_slot_is_passed_through_not_inferred_from_selected(self):
        value = evidence()
        value['booted_slot'] = 'HOST-B'
        value['slots']['HOST-B'] = {
            'generation': 'generation-b',
            'root_partuuid': '11111111-1111-4111-8111-111111111111',
        }
        self.host.report = {'version': 1, 'host_generation': value}
        self.host.save(update_fields=['report'])
        shown = preview(self.host)['host_generation']
        self.assertEqual(shown['selected_slot'], 'HOST-A')
        self.assertEqual(shown['booted_slot'], 'HOST-B')
        self.assertEqual(shown['slots']['HOST-B']['generation'], 'generation-b')
