import json
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from zog.station_access.host_registry.dns_destinations import import_destination,configure
from zog.station_access.host_registry.dns_reconcile import configuration

class Command(BaseCommand):
    help='Import an owned DNS destination or manage an additional host assignment'
    def add_arguments(self,p):
        sub=p.add_subparsers(dest='action',required=True)
        imp=sub.add_parser('import');imp.add_argument('--selection',required=True);imp.add_argument('--ledger',required=True)
        for action in ('reserve','enable','unpublish','release','cancel'):
            s=sub.add_parser(action);s.add_argument('--binding',required=True);s.add_argument('--host',required=True);s.add_argument('--owner',required=True,type=int);s.add_argument('--revision',type=int);s.add_argument('--label')
    def handle(self,*args,**o):
        try:
            if o['action']=='import':result=import_destination(configuration(),json.loads(Path(o['selection']).read_text()),o['ledger'])
            else:result=configure(configuration(),o['binding'],o['host'],o['action'],actor_id=o['owner'],label=o.get('label'),expected_revision=o.get('revision'))
        except Exception as error:raise CommandError('DNS destination change stopped: '+getattr(error,'code',type(error).__name__)) from None
        self.stdout.write(json.dumps(result,default=str))
