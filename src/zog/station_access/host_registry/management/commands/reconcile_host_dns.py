import json
from django.core.management.base import BaseCommand, CommandError
from zog.station_access.host_registry.dns_reconcile import reconcile

class Command(BaseCommand):
    help = 'Reconcile owned host DNS records using the one persistent central controller'
    def add_arguments(self,parser):
        parser.add_argument('--host-id',action='append',help='Evaluate only this reviewed host (shared writer only)')
    def handle(self,*args,**options):
        try:
            result=reconcile(resource_ids=options.get('host_id'))
        except BlockingIOError:
            self.stdout.write('DNS controller busy; next timer run will retry')
            return
        except Exception as error:
            # Do not expose credentials/config contents in unexpected exceptions.
            raise CommandError('DNS reconciliation stopped: '+type(error).__name__+'. Check controller configuration and persistent state.') from None
        self.stdout.write(json.dumps(result,sort_keys=True))
        if any(result.get(k) for k in ('conflict','provider_error','uncertain','failed','pending_other_host')):
            raise CommandError('DNS assignments need attention; see Hosts synchronization status')
