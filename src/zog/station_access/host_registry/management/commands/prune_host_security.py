from django.core.management.base import BaseCommand
from django.utils import timezone
from zog.station_access.host_registry.identity import locked, cleanup
class Command(BaseCommand):
    help='Prune expired enrollment, rate-limit and replay state; preserve approvals and audit'
    def handle(self,*args,**options):
        with locked():cleanup(timezone.now())
        self.stdout.write('Expired security state pruned')
