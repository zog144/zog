from django.core.management.base import BaseCommand, CommandError

from zog.station_access.box_control import get_gateway
from zog.station_access.services.workspaces import reconcile_all_workspaces


class Command(BaseCommand):
    help = "Reconcile station-access VNC workspace desired state with box-control runtimes."

    def handle(self, *args, **options):
        gateway = get_gateway()
        results = reconcile_all_workspaces(gateway)
        failures = 0
        for workspace, state in results:
            if state.status == "fault":
                failures += 1
            self.stdout.write(
                f"{workspace.pk} {workspace.owner_id} {workspace.name!r}: {state.status}"
            )
        if failures:
            raise CommandError(f"{failures} workspace reconciliation failure(s)")
