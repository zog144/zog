"""Read-only tooling and remote environment diagnostics."""
import json
import platform
import boto3
from .provision import configuration
from .runner import Host
from .jobs import shell_python


def local():
    return {'python': platform.python_version(), 'boto3': boto3.__version__}


def remote(directory):
    _, config = configuration(directory)
    code = '''import json,platform,shutil,subprocess
from pathlib import Path
r={'python':platform.python_version(),'architecture':platform.machine(),'disk_free_bytes':shutil.disk_usage('/var/lib').free}
r['tools']={name:shutil.which(name) for name in ['gcc','g++','make','curl','python3','systemctl']}
r['memory']=Path('/proc/meminfo').read_text().splitlines()[:3]
r['systemd']=subprocess.run(['systemctl','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0]
r['expiry_timer']=subprocess.run(['systemctl','is-active','host-deploy-expiry.timer'],capture_output=True,text=True).stdout.strip()
r['uptime_seconds']=float(Path('/proc/uptime').read_text().split()[0])
print(json.dumps(r))'''
    return json.loads(Host(config).command(shell_python(code)))
