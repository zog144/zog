"""Standalone, durable coordination for one normal reboot and two test phases."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time

# Staged alongside this module on the VM; imported relatively during local tests.
try:
    from .job_worker import save, sha, unpack
    from .remote_control import drain, ACTIVE
except ImportError:
    from common import save, sha, unpack
    from control import drain, ACTIVE

OWNER = Path('/var/lib/host-deploy/reboot-owner.json')
RELEASED = {'succeeded', 'failed', 'abandoned'}


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def unit(root, phase):
    return 'host-deploy-reboot-' + root.name + '-' + phase


def active(name):
    result = subprocess.run(['systemctl', 'show', name, '--property=ActiveState', '--value'], capture_output=True, text=True)
    if result.returncode and 'not found' not in result.stderr and 'could not be found' not in result.stderr:
        raise RuntimeError('Cannot inspect systemd: ' + result.stderr)
    return result.stdout.strip() in ACTIVE


def facts():
    timer = subprocess.run(['systemctl', 'is-active', 'host-deploy-expiry.timer'], capture_output=True, text=True)
    enabled = subprocess.run(['systemctl', 'is-enabled', 'host-deploy-expiry.timer'], capture_output=True, text=True)
    return {'boot_id': boot_id(), 'observed_at': time.time(),
            'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
            'expiry_active': timer.returncode == 0, 'expiry_enabled': enabled.returncode == 0,
            'systemd': subprocess.check_output(['systemctl', '--version'], text=True).splitlines()[0]}


def initialize(root):
    if (root/'progress.json').exists(): return observe(root)
    manifest = json.loads((root/'workflow.json').read_text())
    if OWNER.exists():
        owner = json.loads(OWNER.read_text())
        previous = Path(owner['remote_directory'])/'progress.json'
        if owner['workflow_id'] != root.name and (not previous.exists() or json.loads(previous.read_text())['phase'] not in RELEASED):
            raise RuntimeError('Another reboot workflow owns this host')
    # Refuses ordinary active/uncertain jobs and closes ordinary dispatch admission.
    drain()
    state = {'schema': 1, 'workflow_id': root.name, 'phase': 'initializing', 'before_boot_id': boot_id()}
    save(root/'progress.json', state)
    save(OWNER, {'workflow_id': root.name, 'remote_directory': str(root)})
    try:
        before = facts()
        save(root/'before.json', before)
        if not before['expiry_active'] or not before['expiry_enabled']:
            raise RuntimeError('Persistent host expiry timer is not active and enabled')
        if before['uptime_seconds'] + manifest['recipe']['preparation']['timeout_seconds'] + 120 >= manifest['uptime_limit_seconds']:
            raise RuntimeError('Insufficient remaining host uptime for preparation')
        if sha(root/'source.zip') != manifest['source_sha256']: raise ValueError('Source hash mismatch')
        unpack(root/'source.zip', root/'source')
        (root/'state').mkdir()
        state['phase'] = 'ready'
    except Exception as error:
        state.update(phase='failed', reason=str(error))
    save(root/'progress.json', state)
    return state


def snapshot(root, phase, outputs):
    destination = root/(phase+'-state.tar.gz')
    with tarfile.open(destination.with_suffix('.partial'), 'w:gz', dereference=False) as archive:
        for name in outputs:
            source = root/'state'/name
            if source.exists() and source.resolve().is_relative_to((root/'state').resolve()):
                archive.add(source, arcname='state' if name == '.' else 'state/'+name)
    os.replace(destination.with_suffix('.partial'), destination)
    with destination.open('rb') as stream: os.fsync(stream.fileno())


def run_phase(root, phase):
    """Only this service runs test code. A durable status prevents any second run."""
    manifest = json.loads((root/'workflow.json').read_text())
    progress = json.loads((root/'progress.json').read_text())
    expected = progress['before_boot_id' if phase == 'preparation' else 'after_boot_id']
    path = root/(phase+'.json')
    with (root/(phase+'.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists(): return
        result = {'phase': phase, 'state': 'running', 'boot_id': boot_id(), 'started_at': time.time()}
        save(path, result)
        child = None
        def interrupted(signum, frame): raise InterruptedError('Phase interrupted by signal '+str(signum))
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            if result['boot_id'] != expected: raise RuntimeError('Unexpected boot before phase execution')
            environment = os.environ.copy()
            environment.update(manifest['recipe'].get('environment', {}))
            environment.update(HOST_DEPLOY_STATE_DIRECTORY=str(root/'state'),
                               HOST_DEPLOY_BEFORE_BOOT_ID=progress['before_boot_id'],
                               HOST_DEPLOY_AFTER_BOOT_ID=progress.get('after_boot_id', ''),
                               HOST_DEPLOY_PHASE=phase)
            recipe = manifest['recipe'][phase]
            with (root/(phase+'.log')).open('wb') as output:
                child = subprocess.Popen(recipe['command'], cwd=root/'source', env=environment,
                                         stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = child.wait(timeout=recipe['timeout_seconds'])
                    result.update(state='succeeded' if code == 0 else 'failed', return_code=code)
                except subprocess.TimeoutExpired:
                    result['state'] = 'timed_out'
        except Exception as error:
            result.update(state='interrupted' if isinstance(error, InterruptedError) else 'failed', error=str(error))
        finally:
            if child is not None:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
            try:
                snapshot(root, phase, manifest['recipe']['outputs'])
                journal = subprocess.run(['journalctl', '--boot=0', '--no-pager', '-n', '100',
                                          '-u', unit(root, phase)+'.service'], capture_output=True, text=True, timeout=20)
                (root/(phase+'-journal.log')).write_text(journal.stdout + journal.stderr)
            except Exception as error:
                result.update(state='failed', evidence_error=str(error))
            result['finished_at'] = time.time()
            save(path, result)


def observe(root):
    state = json.loads((root/'progress.json').read_text())
    current = boot_id()
    phase = state['phase']
    if phase in RELEASED or phase == 'uncertain': return state
    if phase == 'initializing':
        state.update(phase='uncertain', reason='Initialization was interrupted; preparation was not dispatched')
    elif phase in {'preparation_submitting', 'verification_submitting'}:
        stage = phase.split('_')[0]
        path = root/(stage+'.json')
        running = active(unit(root, stage)+'.service')
        if path.exists():
            result = json.loads(path.read_text())
            state[stage] = result
            if result['state'] != 'running' and not running:
                if result['state'] == 'succeeded':
                    state['phase'] = 'prepared' if stage == 'preparation' else 'succeeded'
                else:
                    state.update(phase='failed', reason=stage+' '+result['state'])
            elif not running:
                state.update(phase='uncertain', reason=stage+' disappeared without a terminal receipt')
        elif not running:
            state.update(phase='uncertain', reason=stage+' dispatch outcome is unknown; refusing replay')
    elif phase in {'reboot_submitting', 'reboot_wait'}:
        limit = state['reboot_requested_at'] + json.loads((root/'workflow.json').read_text())['recipe']['reboot_timeout_seconds']
        if current != state['before_boot_id']:
            after = facts()
            save(root/'after.json', after)
            # The controller may return after the wait window. Measure the actual
            # current boot's start, rather than treating late observation as a late reboot.
            if after['observed_at'] - after['uptime_seconds'] > limit:
                state.update(phase='uncertain', reason='Observed boot began after the reboot deadline')
            elif not after['expiry_active'] or not after['expiry_enabled']:
                state.update(phase='uncertain', reason='Expiry timer not active and enabled after reboot')
            else:
                state.update(phase='rebooted', after_boot_id=current)
        elif time.time() > limit:
            state.update(phase='uncertain', reason='Reboot verification deadline expired; no second reboot will be issued')
    if state['phase'] in {'ready', 'prepared', 'preparation_submitting'} and current != state['before_boot_id']:
        state.update(phase='uncertain', reason='Unexpected reboot before planned reboot request')
    if state['phase'] in {'rebooted', 'verification_submitting'} and current != state['after_boot_id']:
        state.update(phase='uncertain', reason='Additional unexpected reboot before verification completed')
    save(root/'progress.json', state)
    return state


def dispatch_phase(root, state, stage):
    manifest = json.loads((root/'workflow.json').read_text())
    timeout = manifest['recipe'][stage]['timeout_seconds']
    if float(Path('/proc/uptime').read_text().split()[0]) + timeout + 120 >= manifest['uptime_limit_seconds']:
        state.update(phase='failed', reason='Insufficient remaining host uptime for '+stage)
        save(root/'progress.json', state)
        return
    # This write precedes the only dispatch. A lost outcome is never replayed.
    state['phase'] = stage+'_submitting'
    save(root/'progress.json', state)
    subprocess.run(['systemd-run', '--quiet', '--collect', '--unit='+unit(root, stage),
                    '--property=Type=exec', '--property=KillMode=control-group', '--property=TimeoutStopSec=10',
                    '--property=RuntimeMaxSec='+str(timeout+60), '/usr/bin/python3', str(root/'reboot_remote.py'),
                    'phase', str(root), stage], check=True)


def advance(root):
    state = observe(root)
    if state['phase'] == 'ready': dispatch_phase(root, state, 'preparation')
    elif state['phase'] == 'prepared':
        # Verify the service/cgroup is gone before rebooting the host.
        if active(unit(root, 'preparation')+'.service'): return state
        state.update(phase='reboot_submitting', reboot_requested_at=time.time())
        save(root/'progress.json', state)
        os.sync()  # Normal reboot test only; this is not abrupt-power-loss testing.
        subprocess.run(['systemd-run', '--quiet', '--unit='+unit(root, 'request'), '--on-active=5s',
                        '--timer-property=AccuracySec=1s', '/usr/bin/systemctl', 'reboot'], check=True)
        state['phase'] = 'reboot_wait'
        save(root/'progress.json', state)
    elif state['phase'] == 'rebooted': dispatch_phase(root, state, 'verification')
    return state


def abandon(root):
    state = observe(root)
    if state['phase'] in RELEASED: return state
    if 'reboot_requested_at' in state and boot_id() == state['before_boot_id']:
        raise RuntimeError('Reboot may still be queued on this boot; force-stop/start the host before abandonment')
    for stage in ['preparation', 'verification']:
        name = unit(root, stage)+'.service'
        if active(name): subprocess.run(['systemctl', 'stop', name], check=True, timeout=45)
        if active(name): raise RuntimeError('Phase remains active')
    state.update(phase='abandoned', abandoned_at=time.time())
    save(root/'progress.json', state)
    return state


def collect(root):
    state = observe(root)
    if state['phase'] not in RELEASED | {'uncertain'}:
        raise RuntimeError('Workflow still in progress')
    if any(active(unit(root, stage)+'.service') for stage in ['preparation', 'verification']):
        raise RuntimeError('A phase is still active')
    if state['phase'] in {'uncertain', 'abandoned'} and (root/'state').exists():
        manifest = json.loads((root/'workflow.json').read_text())
        snapshot(root, 'recovery', manifest['recipe']['outputs'])
    destination = root/'results.tar.gz'
    cache = root/'results-state.json'
    if destination.exists() and cache.exists() and json.loads(cache.read_text()) == state:
        return {'bytes':destination.stat().st_size,'sha256':sha(destination)}
    with tarfile.open(destination.with_suffix('.partial'), 'w:gz', dereference=False) as archive:
        for name in ['workflow.json', 'progress.json', 'before.json', 'after.json',
                     'preparation.json', 'verification.json', 'preparation.log', 'verification.log',
                     'preparation-state.tar.gz', 'verification-state.tar.gz', 'recovery-state.tar.gz',
                     'preparation-journal.log', 'verification-journal.log']:
            if (root/name).exists(): archive.add(root/name, arcname=name)
    os.replace(destination.with_suffix('.partial'), destination)
    save(cache,state)
    return {'bytes': destination.stat().st_size, 'sha256': sha(destination)}


if __name__ == '__main__':
    action, directory = sys.argv[1:3]
    root = Path(directory)
    if action == 'phase': run_phase(root, sys.argv[3])
    else:
        # Shared with ordinary job dispatch and shutdown admission.
        with Path('/run/host-deploy-control.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = {'initialize': initialize, 'advance': advance, 'observe': observe,
                      'abandon': abandon, 'collect': collect}[action](root)
            print(json.dumps(result))
