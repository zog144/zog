import json
import uuid

from django.http import HttpResponse

from zog.archive_mirror import notice_contract as c
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from zog.station_access.host_registry.views import administrator

from .models import Entry, NoticeBundle
from .views import response


GENERATION_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}"


def _bound_entry(request, generation):
    if set(request.GET) != {"mirror", "snapshot", "collection", "digest"}:
        raise ValueError("Generation query must bind one observed archive item")
    if any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise ValueError("Duplicate generation query parameter")
    c.pattern(generation, GENERATION_PATTERN)
    host = uuid.UUID(request.GET["mirror"])
    snapshot = uuid.UUID(request.GET["snapshot"])
    collection = request.GET["collection"]
    digest = request.GET["digest"]
    c.pattern(collection, r"[a-z0-9][a-z0-9_-]{0,63}")
    c.pattern(digest, c.HEX)
    row = Entry.objects.select_related("observation").get(
        observation_id=snapshot,
        observation__host_id=host,
        observation__complete=True,
        observation__status="ok",
        collection=collection,
        digest=digest,
    )
    if row.metadata.get("kind") != "root-filesystem":
        raise ValueError("Archive item is not a root filesystem")
    if row.metadata.get("version") != generation:
        raise ValueError("Generation identity does not match archive item")
    return host, snapshot, row


def _source_complete(record):
    return bool(record.get("source_digest") and record.get("origin"))


def _license_complete(record):
    if not record.get("expression"):
        return False
    if record.get("review") not in {"declared", "reviewed"}:
        return False
    if record.get("issues"):
        return False
    for part in record.get("exceptions", []):
        if not part.get("expression") or part.get("review") not in {"declared", "reviewed"}:
            return False
    return True


def _coverage(complete, total):
    return {
        "state": "complete" if total == complete else "incomplete",
        "complete": complete,
        "total": total,
    }


def _unknown_coverage():
    return {"state": "unknown", "complete": None, "total": None}


def _package(record):
    source_complete = _source_complete(record)
    license_complete = _license_complete(record)
    return {
        "package": record["package"],
        "version": record["version"],
        "revision": record["revision"],
        "stage": record["stage"],
        "scope": record["scope"],
        "source_digest": record["source_digest"],
        "origin": record["origin"],
        "expression": record["expression"],
        "review": record["review"],
        "exceptions": record["exceptions"],
        "issues": record["issues"],
        "notice_count": len(record["texts"]),
        "receipt_digest": record["receipt_digest"],
        "source_complete": source_complete,
        "license_complete": license_complete,
        "patches": {"state": "not-integrated", "count": None, "items": []},
    }


def _base_payload(generation, host, snapshot, row, summary):
    return {
        "schema": 1,
        "generation": generation,
        "archive": {
            "mirror": str(host),
            "snapshot": str(snapshot),
            "collection": row.collection,
            "digest": row.digest,
            "name": row.metadata.get("name"),
            "size_bytes": row.metadata.get("size_bytes"),
            "availability": row.metadata.get("availability"),
            "provenance": row.metadata.get("provenance"),
            "approval": row.metadata.get("approval"),
            "observed_at": row.observation.observed_at,
        },
        "license_summary": summary,
        "evidence_state": summary.get("state", "unavailable"),
        "source_material": summary.get("source_material", "unknown"),
        "coverage": {
            "source_provenance": _unknown_coverage(),
            "license_evidence": _unknown_coverage(),
            "unresolved_provenance": None,
        },
        "packages": [],
        "patches": {"state": "not-integrated", "count": None, "items": []},
        "build_evidence": {"state": "not-integrated"},
    }


class EvidenceConflict(Exception):
    pass


def provenance_payload(generation, host, snapshot, row):
    """Canonical Generation Detail read model shared by UI and export."""
    summary = row.metadata.get("licenses", c.unavailable())
    payload = _base_payload(generation, host, snapshot, row, summary)
    if summary.get("state") != "available":
        return payload

    stored = NoticeBundle.objects.filter(
        host_id=host,
        collection=row.collection,
        digest=row.digest,
        bundle_digest=summary["bundle_digest"],
    ).first()
    if not stored:
        payload["evidence_state"] = "missing"
        return payload

    value = c.validate(stored.evidence)
    if (
        c.summary(value) != summary
        or value["artifact_kind"] != "root-filesystem"
        or value["source_identity"]["kind"] != "root-filesystem"
        or value["source_identity"]["digest"] != row.digest
        or value["generation"] != generation
    ):
        raise EvidenceConflict("Generation provenance evidence verification failed")

    packages = [_package(record) for record in value["records"]]
    total = len(packages)
    source_complete = sum(1 for item in packages if item["source_complete"])
    license_complete = sum(1 for item in packages if item["license_complete"])
    unresolved = sum(
        1 for item in packages if not item["source_complete"] or not item["license_complete"]
    )
    payload.update(
        evidence_state="available",
        source_material=value["source_material"],
        coverage={
            "source_provenance": _coverage(source_complete, total),
            "license_evidence": _coverage(license_complete, total),
            "unresolved_provenance": unresolved,
        },
        packages=packages,
    )
    return payload


def _export_package(item):
    return {
        **item,
        "exceptions": sorted(
            item["exceptions"],
            key=lambda part: (
                part.get("scope") or "",
                part.get("expression") or "",
                part.get("review") or "",
                part.get("notes") or "",
            ),
        ),
        "issues": sorted(item["issues"]),
        "patches": {
            **item["patches"],
            "items": sorted(
                item["patches"]["items"],
                key=lambda patch: (
                    patch.get("name") or "",
                    patch.get("digest") or "",
                ),
            ),
        },
    }


def export_payload(payload):
    """Stable v1 machine-readable projection of the canonical read model."""
    archive = dict(payload["archive"])
    observed = archive.get("observed_at")
    if hasattr(observed, "isoformat"):
        archive["observed_at"] = observed.isoformat()
    packages = sorted(
        (_export_package(item) for item in payload["packages"]),
        key=lambda item: (
            item.get("package") or "",
            item.get("version") or "",
            item.get("revision") or "",
            item.get("stage") or "",
            item.get("scope") or "",
            item.get("source_digest") or "",
        ),
    )
    return {
        "schema": 1,
        "kind": "zog-generation-provenance",
        "generation": {
            "identity": payload["generation"],
            "rootfs_sha256": payload["archive"]["digest"],
        },
        "archive": archive,
        "evidence": {
            "state": payload["evidence_state"],
            "source_material": payload["source_material"],
            "coverage": payload["coverage"],
            "license_summary": payload["license_summary"],
        },
        "packages": packages,
        "patches": payload["patches"],
        "build_evidence": payload["build_evidence"],
    }


def _load(request, generation):
    host, snapshot, row = _bound_entry(request, generation)
    return provenance_payload(generation, host, snapshot, row)


@never_cache
@require_GET
@administrator
def detail(request, generation):
    try:
        return response(_load(request, generation))
    except EvidenceConflict as error:
        return response({"detail": str(error)}, 409)
    except Entry.DoesNotExist:
        return response({"detail": "Archive snapshot unavailable; refresh observations"}, 409)
    except (ValueError, KeyError, TypeError):
        return response({"detail": "Invalid generation provenance query"}, 400)


@never_cache
@require_GET
@administrator
def export_provenance(request, generation):
    try:
        value = export_payload(_load(request, generation))
        body = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ) + "\n"
        result = HttpResponse(body, content_type="application/json; charset=utf-8")
        result["Cache-Control"] = "no-store"
        result["X-Content-Type-Options"] = "nosniff"
        result["Content-Disposition"] = f'attachment; filename="generation-{generation}.provenance.v1.json"'
        return result
    except EvidenceConflict as error:
        return response({"detail": str(error)}, 409)
    except Entry.DoesNotExist:
        return response({"detail": "Archive snapshot unavailable; refresh observations"}, 409)
    except (ValueError, KeyError, TypeError):
        return response({"detail": "Invalid generation provenance query"}, 400)
