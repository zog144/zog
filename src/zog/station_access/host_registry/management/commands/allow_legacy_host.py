from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from zog.station_access.host_registry.models import Host
from zog.station_access.host_registry.identity import locked, audit

class Command(BaseCommand):
    help='Explicit temporary legacy-only migration window (no archive access, no signed DNS eligibility)'
    def add_arguments(self,p):
        p.add_argument('host_id');p.add_argument('--hours',type=int,required=True);p.add_argument('--actor',required=True)
    def handle(self,*args,**options):
        if not 1<=options['hours']<=168:raise CommandError('Choose 1–168 hours')
        with locked():
            h=Host.objects.get(pk=options['host_id'])
            if h.identities.exists() or not h.token_digest or h.token_revoked:raise CommandError('Not an eligible legacy host')
            if h.legacy_until is not None:raise CommandError('A migration window was already assigned; it cannot be extended')
            h.legacy_until=timezone.now()+timedelta(hours=options['hours']);h.save(update_fields=['legacy_until'])
            audit(options['actor'],'allow-legacy',host=h,until=h.legacy_until.isoformat())
        self.stdout.write('Bounded legacy reporting enabled; archive access remains disabled')
