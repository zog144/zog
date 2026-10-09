"""Operator-controlled review and forward-only DNS cutover; no purchase operations."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from zog.host_identify.storage import read_owned
from zog.station_access.host_registry.dns_reconcile import configuration
from zog.station_access.host_registry import dns_cutover, dns_shared


class Command(BaseCommand):
    help = 'Review/commit/resume a DNS writer migration, inspect local status, or pause the shared writer'
    def add_arguments(self,parser):
        parser.add_argument('action',choices=('review','commit','status','pause','resume','recheck'))
        parser.add_argument('--selection')
        parser.add_argument('--approve-review')
        parser.add_argument('--request-id')
        parser.add_argument('--expected-revision',type=int)
    def handle(self,*args,**options):
        try:
            config=configuration()
            if not config:raise ValueError()
            action=options['action']
            if action=='review':
                data=json.loads(read_owned(Path(options['selection']),0o600))
                result=dns_cutover.review(config,data)
            elif action=='commit':result=dns_cutover.commit(config,options['approve_review'])
            elif action=='status':result=dns_shared.status(config)
            elif action=='pause':result=dns_cutover.pause(config)
            elif action=='resume':result=dns_cutover.resume(config)
            else:
                from zog.station_access.host_registry.dns_reconcile import controller_lock
                with controller_lock(config,modes=('shared',)) as root:
                    selected,source,engine=dns_shared.open_runtime(config,root)
                    row=engine.recheck(selected.connection.owner_id,selected.connection.owner_id,
                        options['request_id'],options['expected_revision'])
                    result=dict(request_id=row['request_id'],state=row['state'],revision=row['revision'],provider_writes=0)
        except Exception:
            raise CommandError('DNS migration stopped. Preserve state and inspect migration status; check selection, reviewed records, authorization and storage. No automatic rollback was attempted.') from None
        self.stdout.write(json.dumps(result,sort_keys=True))
