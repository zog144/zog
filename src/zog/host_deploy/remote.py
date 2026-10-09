"""Runs as root on the disposable host, under an external timeout."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
import tempfile

root = Path(sys.argv[1])
results = root / 'results'
results.mkdir(exist_ok=True)

def run(name, command, cwd=None):
    with (results / (name + '.log')).open('w') as output:
        result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
    return result.returncode

status = {}
try:
    status['environment'] = run('environment', ['bash', '-c', 'cat /etc/os-release; systemctl --version; uname -a; stat -fc %T /sys/fs/cgroup'])
    status['packages'] = run('packages', ['dnf', 'install', '-y', 'python3.11', 'python3.11-pip', 'dbus-daemon'])
    if status['packages']:
        raise RuntimeError('package installation failed')
    source = root / 'source'
    source.mkdir()
    with zipfile.ZipFile(root / 'source.zip') as archive:
        for item in archive.infolist():
            target = (source / item.filename).resolve()
            if not target.is_relative_to(source.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('unsafe archive entry')
        archive.extractall(source)
    subprocess.run(['python3.11', '-m', 'venv', str(root / 'environment')], check=True)
    python = str(root / 'environment/bin/python')
    status['dependencies'] = run('dependencies', [python, '-m', 'pip', 'install', '-e', str(source/'image-build'), '-e', str(source/'box-control')+'[test]'])
    if status['dependencies']:
        raise RuntimeError('dependency installation failed')
    run('dependency-versions', [python, '-m', 'pip', 'freeze'])
    fixture = root / 'rootfs'
    for directory in ['bin','etc','data','tmp','proc','sys','dev']:
        (fixture/directory).mkdir(parents=True, exist_ok=True)
    for executable in ['/bin/sh', '/bin/sleep', '/bin/true']:
        shutil.copy2(executable, fixture / executable.lstrip('/'))
        libraries = subprocess.check_output(['ldd', executable], text=True)
        for library in re.findall(r'(/[^\s()]+)', libraries):
            destination = fixture / library.lstrip('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(library, destination)
    (fixture/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
    (fixture/'etc/group').write_text('root:x:0:\n')
    status['baseline'] = run('baseline', [python,'-m','pytest','-q','--junitxml='+str(results/'baseline.xml')], source)
    short_state = Path(tempfile.mkdtemp(prefix='hd-', dir='/tmp'))
    status['integration'] = run('integration', [python,'-m','pytest','-v','box-control/tests/test_systemd_integration.py','--run-systemd-integration','--systemd-rootfs='+str(fixture),'--basetemp='+str(short_state),'--junitxml='+str(results/'integration.xml')], source)
    shutil.copytree(short_state, results/'pytest-state', symlinks=True, ignore=shutil.ignore_patterns('rootfs', 'root.sock'))
except Exception as error:
    status['error'] = str(error)
finally:
    (results/'status.json').write_text(json.dumps(status, indent=2))
    run('journal', ['journalctl','-b','--no-pager','-n','1500','-o','short-precise'])
    run('units', ['systemctl','list-units','--all','--no-pager'])
