from django.core.management.base import BaseCommand, CommandError
from zog.station_access.host_registry import deployment_jobs
from zog.station_access.host_registry.models import DeploymentJob

class Command(BaseCommand):
    help='Process one bounded batch of explicitly queued deployment jobs.'

    def handle(self,*args,**options):
        if not deployment_jobs.enabled():raise CommandError('HOST_DEPLOY_JOBS_ENABLED is not enabled')
        for identifier in DeploymentJob.objects.filter(state__in=('queued','submitting','running')).order_by('created_at').values_list('pk',flat=True)[:25]:
            deployment_jobs.process(identifier)
        self.stdout.write('Deployment batch inspected.')
