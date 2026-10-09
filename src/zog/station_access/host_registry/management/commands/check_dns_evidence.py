import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from zog.host_identify.storage import read_owned
from zog.station_access.host_registry.dns_evidence import selection, readiness


class Command(BaseCommand):
    help = 'Read-only DNS/host evidence check for an explicit owner, credential, zone, prefix and host selection'
    def add_arguments(self, parser):
        parser.add_argument('--configuration',required=True)
    def handle(self,*args,**options):
        try:
            data=json.loads(read_owned(Path(options['configuration']),0o600))
            result=readiness(selection(data))
        except Exception:
            # DNS, vault and ORM exceptions may contain sensitive input.
            raise CommandError('DNS evidence check blocked. Verify selection, permissions, fresh signed/inventory evidence and DNS authority.') from None
        self.stdout.write(json.dumps(result,sort_keys=True))
        if any(row['evidence']!='ready' for row in result['hosts']):
            raise CommandError('One or more hosts lack current publication evidence; no DNS changes made.')
