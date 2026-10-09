import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from django.core.management.base import BaseCommand, CommandError
from zog.station_access.host_registry.services import enroll
class Command(BaseCommand):
    help = "Enroll a host or rotate its token; write credentials only to a private output file."
    def add_arguments(self, parser):
        for name in ["host-id","account-id","region","instance-id","label","workspace-id"]:
            parser.add_argument("--"+name, default="")
        parser.add_argument("--server",required=True)
        parser.add_argument("--output",required=True)
        parser.add_argument("--ca-file",default="")
    def handle(self,*args,**options):
        url=urlsplit(options["server"])
        if url.scheme!="https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("","/"):
            raise CommandError("Server must be an HTTPS origin")
        fields=[options[k] for k in ["account_id","region","instance_id"]]
        if any(fields) and (not all(fields) or not re.fullmatch(r"[0-9]{12}",fields[0]) or not re.fullmatch(r"[a-z0-9-]{3,40}",fields[1]) or not re.fullmatch(r"i-[a-f0-9]{8,17}",fields[2])):
            raise CommandError("Supply valid AWS account, region and instance ID together")
        if options["host_id"] and any(fields): raise CommandError("Use host-id OR AWS identity")
        if len(options["label"])>200: raise CommandError("Label too long")
        path=Path(options["output"])
        # Refuse overwrite: don't rotate a working token accidentally on a retried command.
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            host,token=enroll(**{key:options[key] for key in ["host_id","account_id","region","instance_id","label","workspace_id"]})
            configuration={"server":options["server"].rstrip("/"),"host_id":str(host.pk),"token":token,"ca_file":options["ca_file"],"provider":host.provider,
                "cloud":{"account_id":host.account_id,"region":host.region,"instance_id":host.instance_id} if host.provider=="aws" else {}}
            with os.fdopen(descriptor,"w") as output:
                json.dump(configuration,output);output.flush();os.fsync(output.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        self.stdout.write("Host enrolled; private configuration written to "+str(path))
