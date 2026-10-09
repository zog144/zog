"""Run only as a declared box-control preparation command inside the test root."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import venv

os.umask(0o077)
data=Path('/var/lib/station-access')
environment=Path('/opt/station-python')
venv.EnvBuilder(with_pip=False).create(environment)
pip=next(Path('/opt/wheels').glob('pip-*.whl'))
bootstrap=dict(os.environ,PYTHONPATH=str(pip))
python=str(environment/'bin/python')
subprocess.run([python,'-m','pip','install','--no-index','--find-links=/opt/wheels',
                'station-access','archive-mirror','box-control','network-register'],env=bootstrap,check=True)
secrets_file=data/'deployment-secrets.json'
if not secrets_file.exists():
    secrets_file.write_text(json.dumps({'django_secret_key':secrets.token_urlsafe(48),'websockify_secret':secrets.token_urlsafe(48)}))
subprocess.run([python,'-m','django','migrate','--noinput'],check=True)
subprocess.run([python,'-m','django','initialize_station'],check=True)
subprocess.run([python,'-m','django','check'],check=True)
(data/'preparation-complete.json').write_text(json.dumps({'version':1,'python_environment':str(environment)}))
