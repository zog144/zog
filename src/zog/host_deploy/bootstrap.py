"""Import explicitly supplied credentials without logging them or overwriting profiles."""
import configparser
import os
from pathlib import Path
import re


def import_credentials(source, destination, profile):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',profile):
        raise ValueError('Invalid profile name')
    values={}
    mapping={'accesskey':'aws_access_key_id','accesskeyid':'aws_access_key_id','awsaccesskeyid':'aws_access_key_id',
             'secretaccesskey':'aws_secret_access_key','awssecretaccesskey':'aws_secret_access_key',
             'sessiontoken':'aws_session_token','awssessiontoken':'aws_session_token'}
    for line in Path(source).read_text().splitlines():
        if not line.strip():
            continue
        label,separator,value=line.partition(':')
        key=mapping.get(re.sub('[^a-z]','',label.lower()))
        if not separator or not key or key in values or not value.strip():
            raise ValueError('Expected unique colon-delimited credential fields')
        values[key]=value.strip()
    if not {'aws_access_key_id','aws_secret_access_key'} <= values.keys():
        raise ValueError('Credential file is missing required fields')
    if not re.fullmatch(r'[A-Z0-9]{16,128}',values['aws_access_key_id']) or '\n' in values['aws_secret_access_key']:
        raise ValueError('Invalid credential structure')
    destination=Path(destination).expanduser()
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if destination.is_symlink():
        raise ValueError('Refusing a symlink credential destination')
    # Serialize imports without truncating an existing profile.
    import fcntl
    import tempfile
    with (destination.parent/'host-deploy-credentials.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        parser=configparser.RawConfigParser()
        if destination.exists():
            parser.read(destination)
        if parser.has_section(profile):
            if dict(parser[profile]) != values:
                raise ValueError('Profile exists with different values; use another profile name')
            os.chmod(destination,0o600)
            return
        parser[profile]=values
        descriptor,temporary=tempfile.mkstemp(prefix='.credentials-',dir=destination.parent)
        try:
            with os.fdopen(descriptor,'w') as output:
                parser.write(output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary,destination)
            directory=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
