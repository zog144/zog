import json
from django.core.management.base import BaseCommand, CommandError
from zog.station_access.host_registry.dns_reconcile import configuration
from zog.station_access.host_registry import dns_membership, dns_shared

class Command(BaseCommand):
    help='Review and commit host DNS enrollment or release; no direct provider writes'
    def add_arguments(self,parser):
        parser.add_argument('action',choices=('review','commit','cancel','status'))
        parser.add_argument('--host-id')
        parser.add_argument('--change',choices=('reserve','release'))
        parser.add_argument('--label')
        parser.add_argument('--approve-review')
    def handle(self,*args,**options):
        try:
            config=configuration()
            if not config:raise ValueError()
            if options['action']=='status':result=dns_shared.status(config)
            elif options['action']=='review':result=dns_membership.review(config,options['host_id'],options['change'],options['label'])
            else:result=getattr(dns_membership,options['action'])(config,options['approve_review'])
        except Exception:
            raise CommandError('DNS membership change stopped. Inspect status and retain the review ID; retry the same commit to resume. Cancellation is permitted only before allocation changes.') from None
        self.stdout.write(json.dumps(result,sort_keys=True))
