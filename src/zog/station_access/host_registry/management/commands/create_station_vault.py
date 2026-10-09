import base64,json,os
from pathlib import Path
from django.core.management.base import BaseCommand
class Command(BaseCommand):
    help='Create a new owner-only vault keyring, separate from the database. Never overwrite an existing keyring.'
    def add_arguments(self,p):p.add_argument('path')
    def handle(self,*args,**options):
        from zog.host_identify.storage import directory,sync_directory
        path=Path(options['path']);directory(path.parent)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:
            json.dump({'active':'vault-1','keys':{'vault-1':base64.b64encode(os.urandom(32)).decode()}},f)
            f.flush();os.fsync(f.fileno())
        sync_directory(path.parent);self.stdout.write('Vault keyring created; keep it out of archives and database backups')
