import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from zog.host_install.state_contract import StateError, digest, host_slots, validate
from zog.host_install.state_inspect import host_generation_report

BUNDLE = json.loads((Path(__file__).resolve().parents[1] / 'examples/state-contract-v1/bundle.json').read_text())


class Context:
    def __init__(self, bundle):
        self.bundle = bundle
        self.checks = 0

    def recheck(self):
        self.checks += 1


def extended():
    bundle = copy.deepcopy(BUNDLE)
    r = bundle['installation']['installer_recorded']
    r['host_slots'] = {
        'HOST-A': {
            'generation': r['expected_host_generation'],
            'root_partuuid': r['root_partuuid'],
        },
        'HOST-B': {
            'generation': 'previous-generation',
            'root_partuuid': '11111111-1111-4111-8111-111111111111',
        },
    }
    bundle['bootstrap']['installation_record']['sha256'] = digest(bundle['installation'])
    return bundle


class HostGenerationTests(unittest.TestCase):
    def test_legacy_record_normalizes_unknown_inactive_slot(self):
        validate(BUNDLE)
        slots = host_slots(BUNDLE['installation'])
        self.assertEqual(slots['HOST-A']['generation'], 'synthetic-generation-1')
        self.assertIsNone(slots['HOST-B'])

    def test_extended_slot_map_binds_selected_record_and_preserves_inactive_generation(self):
        bundle = extended()
        validate(bundle)
        slots = host_slots(bundle['installation'])
        self.assertEqual(slots['HOST-A']['generation'], 'synthetic-generation-1')
        self.assertEqual(slots['HOST-B']['generation'], 'previous-generation')

    def test_slot_map_cannot_disagree_with_selected_generation_or_reuse_partition(self):
        bundle = extended()
        bundle['installation']['installer_recorded']['host_slots']['HOST-A']['generation'] = 'wrong'
        bundle['bootstrap']['installation_record']['sha256'] = digest(bundle['installation'])
        with self.assertRaisesRegex(StateError, 'slot-binding'):
            validate(bundle)

        bundle = extended()
        bundle['installation']['installer_recorded']['host_slots']['HOST-B']['root_partuuid'] = (
            bundle['installation']['installer_recorded']['root_partuuid']
        )
        bundle['bootstrap']['installation_record']['sha256'] = digest(bundle['installation'])
        with self.assertRaisesRegex(StateError, 'slot PARTUUID reused'):
            validate(bundle)

    def test_generation_report_proves_booted_slot_from_live_root_partuuid(self):
        bundle = extended()
        context = Context(bundle)
        with patch(
            'zog.host_install.state_inspect.root_partition_partuuid',
            return_value='11111111-1111-4111-8111-111111111111',
        ):
            value = host_generation_report(context)
        self.assertEqual(value['source'], 'verified-host-install-state-v1')
        self.assertEqual(value['selected_slot'], 'HOST-A')
        self.assertEqual(value['booted_slot'], 'HOST-B')
        self.assertEqual(value['slots']['HOST-A']['generation'], 'synthetic-generation-1')
        self.assertEqual(value['slots']['HOST-B']['generation'], 'previous-generation')
        self.assertEqual(value['installation'], {
            'installation_id': '00000001-0001-4001-8001-000000000001',
            'record_id': '00000005-0005-4005-8005-000000000005',
            'record_schema': 1,
            'operation': 'fresh',
        })
        self.assertEqual(value['transitional_boot_bundle']['record_sha256'], 'b' * 64)
        self.assertEqual(context.checks, 2)

    def test_transitional_root_is_not_mislabeled_as_host_slot(self):
        context = Context(copy.deepcopy(BUNDLE))
        with patch(
            'zog.host_install.state_inspect.root_partition_partuuid',
            return_value='99999999-9999-4999-8999-999999999999',
        ):
            value = host_generation_report(context)
        self.assertIsNone(value['booted_slot'])
        self.assertEqual(value['selected_slot'], 'HOST-A')
        self.assertIsNone(value['slots']['HOST-B'])

    def test_slot_switch_transition_requires_preserved_previous_slot(self):
        from zog.host_install.state_provision import transition

        previous = copy.deepcopy(BUNDLE)
        new = copy.deepcopy(BUNDLE)
        r = new['installation']['installer_recorded']
        new['installation']['operation'] = 'upgrade'
        new['installation']['record_id'] = '99999999-9999-4999-8999-999999999999'
        new['bootstrap']['configuration_revision'] = 2
        new['bootstrap']['mode'] = 'existing'
        r['expected_slot'] = 'HOST-B'
        r['expected_host_generation'] = 'synthetic-generation-2'
        r['root_partuuid'] = '22222222-2222-4222-8222-222222222222'
        r['host_slots'] = {
            'HOST-A': {
                'generation': previous['installation']['installer_recorded']['expected_host_generation'],
                'root_partuuid': previous['installation']['installer_recorded']['root_partuuid'],
            },
            'HOST-B': {
                'generation': r['expected_host_generation'],
                'root_partuuid': r['root_partuuid'],
            },
        }
        new['bootstrap']['installation_record']['sha256'] = digest(new['installation'])
        transition(new, previous)

        broken = copy.deepcopy(new)
        broken['installation']['installer_recorded']['host_slots']['HOST-A'] = None
        broken['bootstrap']['installation_record']['sha256'] = digest(broken['installation'])
        with self.assertRaisesRegex(StateError, 'inactive host slot provenance changed'):
            transition(broken, previous)

    def test_known_slot_map_cannot_be_dropped_on_later_transition(self):
        from zog.host_install.state_provision import transition

        previous = extended()
        new = copy.deepcopy(previous)
        new['installation']['operation'] = 'upgrade'
        new['installation']['record_id'] = '88888888-8888-4888-8888-888888888888'
        new['bootstrap']['configuration_revision'] = 2
        new['bootstrap']['mode'] = 'existing'
        del new['installation']['installer_recorded']['host_slots']
        new['bootstrap']['installation_record']['sha256'] = digest(new['installation'])
        with self.assertRaisesRegex(StateError, 'known slot provenance cannot be dropped'):
            transition(new, previous)


if __name__ == '__main__':
    unittest.main()
