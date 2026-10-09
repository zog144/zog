"""Remote stdlib control helpers. Operations are serialized by the caller's flock."""
import json
from pathlib import Path
import subprocess
import sys

ACTIVE = {'active', 'activating', 'deactivating', 'reloading'}
TERMINAL = {'succeeded', 'failed', 'timed_out', 'interrupted', 'cancelled'}


def status(root, unit):
    result = {'state': 'not_submitted'}
    if (root/'dispatch.json').exists():
        result = json.loads((root/'dispatch.json').read_text())
        result['state'] = 'submission_uncertain'
    if (root/'status.json').exists():
        result = json.loads((root/'status.json').read_text())
    value = subprocess.run(['systemctl', 'show', unit, '--property=ActiveState', '--value'], capture_output=True, text=True)
    # A missing collected unit is inactive; other errors must not authorize shutdown.
    if value.returncode and 'could not be found' not in value.stderr and 'not found' not in value.stderr:
        raise RuntimeError('Cannot inspect systemd unit: ' + value.stderr)
    result['unit_state'] = value.stdout.strip() or 'inactive'
    if result['state'] == 'running' and result['unit_state'] not in ACTIVE:
        result.update(state='interrupted', reason='Worker no longer active without a terminal result')
    if (root/'cancel.json').exists() and result['unit_state'] not in ACTIVE and result['state'] not in {'succeeded', 'failed', 'timed_out'}:
        result['state'] = 'cancelled'
    if (root/'publication.json').exists():
        result['publication'] = json.loads((root/'publication.json').read_text())
    return result


def reboot_busy():
    owner = Path('/var/lib/host-deploy/reboot-owner.json')
    if not owner.exists(): return False
    state = Path(json.loads(owner.read_text())['remote_directory'])/'progress.json'
    return not state.exists() or json.loads(state.read_text())['phase'] not in {'succeeded','failed','abandoned'}


def drain():
    if reboot_busy(): raise RuntimeError('Reboot workflow prevents shutdown or concurrent job dispatch')
    blockers = []
    for root in Path('/var/lib/host-deploy/jobs').glob('*'):
        if not root.is_dir(): continue
        unit = 'host-deploy-job-' + root.name + '.service'
        value = status(root, unit)
        if value['unit_state'] in ACTIVE or value['state'] == 'submission_uncertain':
            blockers.append(root.name)
    # Include orphan units absent from the job directory inventory.
    units = subprocess.run(['systemctl', 'list-units', '--all', '--plain', '--no-legend', '--no-pager', 'host-deploy-job-*.service'], check=True, capture_output=True, text=True)
    for line in units.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[2] in ACTIVE:
            blockers.append(fields[0])
    if blockers:
        raise RuntimeError('Active or uncertain jobs prevent shutdown: ' + ', '.join(blockers))
    Path('/run/host-deploy-draining').touch(mode=0o600)
    print(json.dumps({'draining': True}))


if __name__ == '__main__':
    if sys.argv[1] == 'drain': drain()
