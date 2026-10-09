"""Local administrative export; verifies the password against the current Django user."""
import json,os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from zog.host_identify.storage import atomic,directory,read_owned
class Command(BaseCommand):
    help='Export verified station-admin credentials to an owner-only file for trusted beacon provisioning'
    def add_arguments(self,p):
        p.add_argument('--source',help='Owner-only FIRST-LOGIN.txt or JSON credential file')
        p.add_argument('--output',required=True)
    def handle(self,*args,**options):
        source=Path(options['source'] or Path(settings.STATE_DIRECTORY)/'FIRST-LOGIN.txt')
        try:
            text=read_owned(source,0o600).decode()
            if text.lstrip().startswith('{'):value=json.loads(text)
            else:
                fields=dict(line.split(': ',1) for line in text.splitlines() if ': ' in line)
                value={'username':fields['Username'],'password':fields['Password']}
            user=get_user_model().objects.get(username='station-admin')
            if value['username']!='station-admin' or not user.is_active or not user.is_superuser or not user.check_password(value['password']):raise ValueError()
            target=Path(options['output']);directory(target.parent)
            atomic(target,json.dumps({'username':'station-admin','password':value['password']}).encode())
        except Exception:raise CommandError('Export failed: check source permissions and current station-admin credentials') from None
        self.stdout.write('Credential export written; provision privately to the beacon account')
