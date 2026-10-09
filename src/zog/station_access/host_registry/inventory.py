"""Read all EC2 instances; commit each region only after all pages succeed."""
from django.db import transaction
from django.utils import timezone
from .models import Host, InventoryScan

def error_code(error):
    return (getattr(error,"response",None) or {}).get("Error",{}).get("Code",type(error).__name__)[:500]

def scan_inventory(session):
    from botocore.config import Config
    config = Config(connect_timeout=5,read_timeout=15,retries={"total_max_attempts":2})
    now = timezone.now()
    discovery, _ = InventoryScan.objects.get_or_create(scope="region-discovery")
    discovery.last_attempt=now
    discovery.save(update_fields=["last_attempt"])
    try:
        account = session.client("sts",config=config).get_caller_identity()["Account"]
        regions = sorted(item["RegionName"] for item in session.client("ec2",config=config).describe_regions(AllRegions=False)["Regions"])
    except Exception as error:
        discovery.error=error_code(error); discovery.save(update_fields=["error"])
        return False
    discovery.error=""; discovery.last_success=timezone.now(); discovery.save(update_fields=["error","last_success"])
    InventoryScan.objects.update_or_create(scope=account+"/region-discovery",
        defaults={"last_attempt":now,"last_success":timezone.now(),"error":""})
    for region in regions:
        InventoryScan.objects.get_or_create(scope=account+"/"+region)
    success = True
    for region in regions:
        record = InventoryScan.objects.get(scope=account+"/"+region)
        record.last_attempt=timezone.now(); record.save(update_fields=["last_attempt"])
        try:
            client = session.client("ec2",region_name=region,config=config)
            instances = [instance for page in client.get_paginator("describe_instances").paginate() for reservation in page["Reservations"] for instance in reservation["Instances"]]
            commit_region(account,region,instances,record)
        except Exception as error:
            success=False; record.error=error_code(error); record.save(update_fields=["error"])
    return success

from .identity import locked

@locked()
def commit_region(account,region,instances,record):
    now = timezone.now()
    identifiers = []
    for instance in instances:
        identifier=instance["InstanceId"]; identifiers.append(identifier)
        tags={item["Key"]:item["Value"] for item in instance.get("Tags",[])}
        host, _ = Host.objects.get_or_create(provider="aws",account_id=account,region=region,instance_id=identifier,
            defaults={"label":tags.get("Name",identifier)[:200]})
        observation={"cloud":{"account_id":account,"region":region,"instance_id":identifier},
            "observed_at":(record.last_attempt or now).isoformat(),"state":instance["State"]["Name"],"public_dns":instance.get("PublicDnsName",""),
            "public_ip":instance.get("PublicIpAddress",""),"private_dns":instance.get("PrivateDnsName",""),
            "private_ip":instance.get("PrivateIpAddress",""),"instance_type":instance.get("InstanceType",""),
            "tags":tags,"volume_ids":[item["Ebs"]["VolumeId"] for item in instance.get("BlockDeviceMappings",[]) if "Ebs" in item]}
        Host.objects.filter(pk=host.pk).update(aws_observation=observation,aws_checked_at=now,aws_missing_since=None,workspace_id=tags.get("ZogWorkspace",host.workspace_id))
    # Disappearance is not evidence of termination; retain history and mark observation unknown.
    Host.objects.filter(provider="aws",account_id=account,region=region,aws_missing_since__isnull=True).exclude(instance_id__in=identifiers).update(aws_missing_since=now)
    record.last_success=now;record.error="";record.instance_count=len(instances);record.save()
