import json
from zog.network_register.contracts import NetworkError
import hmac
import re
from functools import wraps
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.core.exceptions import RequestDataTooBig
from .models import Host, InventoryScan, DnsAssignment
from .services import digest

HOSTNAME = re.compile(r"(?=.{1,253}\Z)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\Z")

def administrator(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail":"Login required"}, status=401)
        if not request.user.is_superuser:
            return JsonResponse({"detail":"Administrator access required"}, status=403)
        return view(request, *args, **kwargs)
    return wrapped

def body(request):
    if request.content_type != "application/json":
        raise ValueError("Expected application/json")
    if int(request.META.get("CONTENT_LENGTH") or 0) > 16384:
        raise ValueError("Request too large")
    raw = request.body
    if len(raw) > 16384:
        raise ValueError("Request too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value

def serialize(host, now):
    age = (now-host.last_received).total_seconds() if host.last_received else None
    observation = host.aws_observation
    fresh = bool(host.aws_checked_at and (now-host.aws_checked_at).total_seconds() <= 600 and not host.aws_missing_since)
    tags = observation.get("tags", {})
    tagged = tags.get("Project", "").lower()=="zog" or tags.get("ManagedBy")=="host-deploy" or bool(tags.get("ZogWorkspace"))
    tag_status = ("zog" if tagged else "untagged") if fresh and "tags" in observation else "unknown"
    # Use reporter addresses only before any authoritative AWS address observation.
    # In particular, never resurrect an older report after AWS clears an address.
    use_inventory = host.provider == "aws" and host.aws_checked_at is not None
    address_data = observation if use_inventory else host.report
    address = address_data.get("public_dns") or address_data.get("public_ip") or ""
    address_source = "aws" if use_inventory else "heartbeat" if host.last_received else "unknown"
    address_stale = not fresh if use_inventory else age is None or age > 180
    from .dns_reconcile import serialize_assignment
    from .dns_destinations import serialize as serialize_additional
    assignment = getattr(host, 'dns_assignment', None)
    from . import vault, mirror_roles
    return {"archived_at":host.archived_at,"archived_by":host.archived_by,"station_login":vault.metadata(host),"mirror_role":mirror_roles.serialize(host,now),"dns":serialize_assignment(assignment) if assignment else None, "additional_dns":[serialize_additional(a) for a in host.additional_dns_assignments.select_related("binding").all()], "id":str(host.id), "label":host.label, "provider":host.provider,
        "account_id":host.account_id, "region":host.region, "instance_id":host.instance_id,
        "tag_status":tag_status, "public_address":address, "address_source":address_source,
        "address_stale":address_stale,
        "workspace_id":host.workspace_id, "first_seen":host.first_seen, "last_received":host.last_received,
        "heartbeat":"never" if age is None else "recent" if age <= 180 else "overdue",
        "report":host.report, "aws":observation, "aws_checked_at":host.aws_checked_at,
        "aws_missing_since":host.aws_missing_since, "aws_fresh":fresh,
        "aws_state":observation.get("state", "unknown") if fresh else "unknown",
        "zog_tagged":tagged,
        "enrolled":host.identities.filter(status="approved").exists()}

def inventory_status(scans, now):
    discovery = next((scan for scan in scans if scan["scope"] == "region-discovery"), None)
    regional = [scan for scan in scans if scan["scope"] != "region-discovery"]
    def recent(scan):
        return bool(scan["last_success"] and (now-scan["last_success"]).total_seconds() <= 600)
    fresh_regions = [scan for scan in regional if recent(scan)]
    if not fresh_regions:
        return "unavailable"
    complete = bool(discovery and recent(discovery) and not discovery["error"] and regional and all(
        recent(scan) and not scan["error"] and scan["last_success"] >= discovery["last_success"] for scan in regional))
    return "complete" if complete else "partial"

@require_GET
@administrator
def hosts(request):
    now = timezone.now()
    scans = list(InventoryScan.objects.order_by("scope").values("scope","last_attempt","last_success","error","instance_count"))
    from .dns_reconcile import configuration
    try:
        config = configuration()
        from .dns_cutover import controller_state
        writer=controller_state(config)['writer'] if config else ''
        dns_config = {"writer":writer,"configured":bool(config), "suffix":config['suffix'] if config else '', "auto_publish_enrolled":bool(config and config.get('auto_publish_enrolled')), "error":''}
    except (OSError,ValueError,KeyError,NetworkError):
        dns_config = {"configured":False,"suffix":'',"auto_publish_enrolled":False,"error":"DNS controller configuration unavailable"}
    records=list(Host.objects.select_related('dns_assignment').all())
    from .retirement import duplicate_candidates
    candidates=duplicate_candidates(records)
    response = JsonResponse({"dns":dns_config, "hosts":[serialize(host, now) | {'duplicate_candidates':candidates.get(str(host.pk),[])} for host in records],
        "scans":scans, "inventory_status":inventory_status(scans, now), "server_time":now})
    response["Cache-Control"] = "no-store"
    return response

@require_POST
@administrator
def label(request, host_id):
    try:
        value = body(request)
        if set(value) != {"label"} or not isinstance(value["label"],str) or len(value["label"]) > 200:
            raise ValueError("Supply a label of at most 200 characters")
    except (ValueError, UnicodeError, RequestDataTooBig) as error:
        return JsonResponse({"detail":str(error)}, status=400)
    if not Host.objects.filter(pk=host_id,archived_at__isnull=True).update(label=value["label"].strip()):
        return JsonResponse({"detail":"Host not found"},status=404)
    return JsonResponse({"saved":True})

@csrf_exempt
@require_POST
def legacy_heartbeat(request, host_id):
    # Machine token is the only accepted credential; browser sessions do not authorize this endpoint.
    from .identity import locked
    # Explicit per-host deadline only; approval automatically disables legacy.
    host = Host.objects.filter(pk=host_id, archived_at__isnull=True, legacy_until__gt=timezone.now()).first()
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    if len(token) > 200 or not host or host.token_revoked or not token or not hmac.compare_digest(digest(token),host.token_digest):
        return JsonResponse({"detail":"Invalid host credential"},status=401)
    try:
        value = body(request)
        validate_report(value, host)
    except (ValueError, UnicodeError, RequestDataTooBig) as error:
        return JsonResponse({"detail":str(error)}, status=400)
    now = timezone.now()
    # Conditional write prevents a concurrent credential revocation/rotation from being bypassed.
    with locked():
        updated = Host.objects.filter(pk=host.pk, archived_at__isnull=True, token_digest=host.token_digest, token_revoked=False, legacy_until__gt=now).update(report=value,last_received=now)
    return JsonResponse({"received_at":now},status=200) if updated else JsonResponse({"detail":"Credential changed"},status=401)


@require_POST
@administrator
def dns_configuration(request, host_id):
    from .dns_reconcile import configuration, configure_assignment, serialize_assignment
    try:
        value=body(request)
        if set(value)-{'enabled','label'} or type(value.get('enabled')) is not bool or ('label' in value and not isinstance(value['label'],str)):
            raise ValueError('Supply enabled and optionally an initial DNS label')
        config=configuration()
        if not config:
            return JsonResponse({'detail':'DNS controller is not configured'},status=503)
        host=Host.objects.filter(pk=host_id).first()
        if not host: return JsonResponse({'detail':'Host not found'},status=404)
        if host.provider != 'aws' or (value['enabled'] and not host.identities.filter(status='approved').exists()) or (not value['enabled'] and not DnsAssignment.objects.filter(host=host).exists()):
            raise ValueError('DNS publication requires an enrolled AWS host')
        assignment=configure_assignment(host,config,value['enabled'],value.get('label'))
        return JsonResponse({'dns':serialize_assignment(assignment)})
    except NetworkError as error:
        return JsonResponse({'detail':'DNS controller change stopped: '+error.code},status=409)
    except BlockingIOError:
        return JsonResponse({'detail':'DNS reconciliation is in progress; retry shortly'},status=409)
    except (ValueError,UnicodeError,RequestDataTooBig) as error:
        return JsonResponse({'detail':str(error)},status=400)
    except (OSError,KeyError):
        return JsonResponse({'detail':'DNS controller state unavailable; restore state before changing assignments'},status=503)

def _canonical_uuid(value):
    import uuid
    return isinstance(value, str) and str(uuid.UUID(value)) == value


def validate_host_generation(value):
    if not isinstance(value, dict) or set(value) != {
        "schema", "source", "installation", "selected_slot", "booted_slot",
        "slots", "transitional_boot_bundle",
    }:
        raise ValueError("Invalid host generation evidence")
    if value["schema"] != 1 or value["source"] != "verified-host-install-state-v1":
        raise ValueError("Unsupported host generation evidence")
    installation = value["installation"]
    if not isinstance(installation, dict) or set(installation) != {
        "installation_id", "record_id", "record_schema", "operation",
    }:
        raise ValueError("Invalid installation identity")
    if not _canonical_uuid(installation["installation_id"]) or not _canonical_uuid(installation["record_id"]):
        raise ValueError("Invalid installation identity")
    if installation["record_schema"] != 1 or installation["operation"] not in {
        "fresh", "upgrade", "reinstall", "migration", "recovery",
    }:
        raise ValueError("Unsupported installation record")
    if value["selected_slot"] not in {"HOST-A", "HOST-B"}:
        raise ValueError("Invalid selected host slot")
    if value["booted_slot"] not in {None, "HOST-A", "HOST-B"}:
        raise ValueError("Invalid booted host slot")
    slots = value["slots"]
    if not isinstance(slots, dict) or set(slots) != {"HOST-A", "HOST-B"}:
        raise ValueError("Invalid host slot evidence")
    seen = set()
    generation_pattern = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
    for slot in ("HOST-A", "HOST-B"):
        row = slots[slot]
        if row is None:
            continue
        if not isinstance(row, dict) or set(row) != {"generation", "root_partuuid"}:
            raise ValueError("Invalid host slot evidence")
        if not isinstance(row["generation"], str) or not generation_pattern.fullmatch(row["generation"]):
            raise ValueError("Invalid host generation identity")
        if not _canonical_uuid(row["root_partuuid"]) or row["root_partuuid"] in seen:
            raise ValueError("Invalid host slot partition identity")
        seen.add(row["root_partuuid"])
    if slots[value["selected_slot"]] is None:
        raise ValueError("Selected host slot has no generation identity")
    if value["booted_slot"] is not None and slots[value["booted_slot"]] is None:
        raise ValueError("Booted host slot has no generation identity")
    boot = value["transitional_boot_bundle"]
    if boot is not None:
        if not isinstance(boot, dict) or set(boot) != {
            "kind", "provider", "record_reference", "record_sha256",
        }:
            raise ValueError("Invalid transitional boot bundle")
        if boot["kind"] != "foreign" or not isinstance(boot["provider"], str) or not 0 < len(boot["provider"]) <= 128:
            raise ValueError("Invalid transitional boot bundle")
        if not _canonical_uuid(boot["record_reference"]) or not re.fullmatch(r"[0-9a-f]{64}", boot["record_sha256"]):
            raise ValueError("Invalid transitional boot bundle")


def validate_report(value, host, *, allow_host_generation=False):
    allowed = {"version","hostname","public_dns","public_ip","private_ip","boot_id","daemon_version","cloud","host_generation"}
    if set(value)-allowed or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Unsupported heartbeat schema")
    for field in allowed-{"version","cloud","host_generation"}:
        if field in value and (not isinstance(value[field],str) or len(value[field]) > 253):
            raise ValueError("Invalid "+field)
    for field in ["public_dns","hostname"]:
        if value.get(field) and not HOSTNAME.fullmatch(value[field]):
            raise ValueError("Invalid hostname")
    import ipaddress
    for field in ["public_ip","private_ip"]:
        if value.get(field): ipaddress.ip_address(value[field])
    if "host_generation" in value:
        if not allow_host_generation:
            raise ValueError("Host generation evidence requires signed host identity")
        validate_host_generation(value["host_generation"])
    cloud = value.get("cloud",{})
    if not isinstance(cloud,dict) or set(cloud)-{"account_id","region","instance_id"}:
        raise ValueError("Invalid cloud identity")
    if host.provider == "aws" and cloud != {"account_id":host.account_id,"region":host.region,"instance_id":host.instance_id}:
        raise ValueError("Cloud identity does not match enrollment")
    if host.provider != "aws" and cloud:
        raise ValueError("Cloud identity requires cloud enrollment")
