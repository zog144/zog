import fcntl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from zog.station_access.host_registry.inventory import scan_inventory
class Command(BaseCommand):
    help = "Scan every enabled AWS region using the default AWS credential chain."
    def handle(self,*args,**options):
        import boto3
        with (settings.STATE_DIRECTORY/"host-inventory.lock").open("a") as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise CommandError("Inventory scan already running")
            if not scan_inventory(boto3.Session(region_name="us-east-1")):
                raise CommandError("Inventory incomplete; see per-region status on Hosts page")
        self.stdout.write("Inventory scan complete")
