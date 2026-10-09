"""Schema 1 validation and portable, content-addressed record identities."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any, TypedDict

MAX_RECORD_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 10000
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
ENVIRONMENT = frozenset({"CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS",
                         "LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH", "PATH", "MAKEFLAGS"})
RELATIONSHIPS = frozenset({
    "needs-library", "provides-soname", "elf-interpreter", "script-interpreter",
    "declares-build-dependency", "declares-test-dependency",
    "declares-runtime-dependency", "used-build-output",
})
PACKAGE_RELATIONSHIPS = frozenset({
    "declares-build-dependency", "declares-test-dependency",
    "declares-runtime-dependency", "used-build-output",
})
COVERAGE_FAMILIES = frozenset({
    "verification-commands", "elf-interfaces", "script-interpreters",
    "declared-package-dependencies", "used-build-output", "source-provenance",
})
COVERAGE_OUTCOMES = frozenset({
    "complete", "partial", "unavailable", "not-performed", "not-applicable",
})
SNAPSHOT_GROUPS = {
    "verification_checks": "verification-check",
    "verification_executions": "verification-execution",
    "relationships": "relationship-observation",
    "source_provenance": "source-provenance",
    "coverage": "observation-coverage",
}


class RecordError(ValueError):
    """An invalid record, inconsistent graph or unavailable local object."""


class Record(TypedDict):
    schema_version: int
    kind: str
    data: dict[str, Any]
    gaps: list[str]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def text(value: Any) -> None:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 8192,
            "expected nonempty string of at most 8192 characters")


def digest(value: Any) -> None:
    require(isinstance(value, str) and DIGEST.fullmatch(value) is not None,
            "expected lowercase sha256 digest")


def fields(value: Any, names: str) -> None:
    require(type(value) is dict and set(value) == set(names.split()),
            "unexpected or missing object fields: expected " + names)


def strings(value: Any, *, nonempty: bool = False) -> None:
    require(type(value) is list and (bool(value) or not nonempty), "expected string list")
    for item in value:
        text(item)
    require(len(value) == len(set(value)), "duplicate list entry")


def refs(value: Any, *, nonempty: bool = False) -> None:
    strings(value, nonempty=nonempty)
    for item in value:
        digest(item)


def timestamp(value: Any) -> datetime:
    text(value)
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", value) is not None,
            "timestamp must use UTC YYYY-MM-DDTHH:MM:SS[.ffffff]Z")
    candidate = value[:-1] + "+00:00"
    format_string = ("%Y-%m-%dT%H:%M:%S.%f%z"
                     if "." in value else "%Y-%m-%dT%H:%M:%S%z")
    try:
        result = datetime.strptime(candidate, format_string)
    except ValueError:
        raise RecordError("invalid timestamp") from None
    return result


def observation_timestamp(value: Any) -> datetime:
    """Validate a producer-observed UTC time without rewriting its representation."""
    text(value)
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise RecordError("invalid observation timestamp") from None
    require(result.tzinfo is not None and result.utcoffset() is not None and
            result.utcoffset().total_seconds() == 0,
            "observation timestamp must be UTC")
    return result


def artifact(value: Any) -> None:
    fields(value, "name digest size")
    text(value["name"])
    digest(value["digest"])
    require(type(value["size"]) is int and value["size"] >= 0, "invalid artifact size")


def artifacts(value: Any, *, nonempty: bool = False) -> None:
    require(type(value) is list and (bool(value) or not nonempty), "expected artifact list")
    for item in value:
        artifact(item)
    require(len({item["name"] for item in value}) == len(value), "duplicate artifact name")


def output_bindings(value: Any, *, nonempty: bool = False) -> None:
    require(type(value) is list and (bool(value) or not nonempty), "expected output bindings")
    for item in value:
        fields(item, "output result")
        digest(item["output"])
        if item["result"] is not None:
            digest(item["result"])
    require(len({x["output"] for x in value}) == len(value), "duplicate package output")


def revision(value: Any) -> None:
    require(isinstance(value, str) and REVISION.fullmatch(value) is not None,
            "expected full lowercase Git revision")


def _json_value(value: Any, depth: int = 0) -> None:
    require(depth <= 32, "maximum JSON nesting exceeded")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        require(abs(value) <= 9007199254740991, "integer outside interoperable range")
    elif type(value) is str:
        require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), "invalid Unicode surrogate")
    elif type(value) is list:
        for child in value:
            _json_value(child, depth + 1)
    elif type(value) is dict:
        for key, child in value.items():
            require(type(key) is str, "JSON keys must be strings")
            _json_value(key, depth + 1)
            _json_value(child, depth + 1)
    else:
        raise RecordError("unsupported JSON type (floats are forbidden)")


def canonical(value: Any) -> bytes:
    """Zog encoding: sorted keys, compact ASCII JSON, no floats or normalization."""
    _json_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def loads(raw: bytes | str, limit: int = MAX_RECORD_BYTES) -> Any:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    require(len(raw) <= limit, "JSON byte limit exceeded")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        _json_value(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, RecordError):
            raise
        raise RecordError("invalid JSON") from None


def snapshot_record_set_digest(generation: str, observations: dict) -> str:
    """Digest the exact canonical record set included by a generation snapshot."""
    digest(generation)
    fields(observations, "verification_checks verification_executions relationships source_provenance coverage")
    identities = []
    for group in SNAPSHOT_GROUPS:
        refs(observations[group])
        require(observations[group] == sorted(observations[group]),
                "snapshot observation IDs must be sorted")
        identities.extend(observations[group])
    require(len(identities) == len(set(identities)),
            "snapshot record cannot appear in multiple observation groups")
    payload = {"generation": generation, "records": sorted(identities)}
    return "sha256:" + hashlib.sha256(canonical(payload)).hexdigest()


def validate(record: Any) -> None:
    require(len(canonical(record)) <= MAX_RECORD_BYTES, "record byte limit exceeded")
    fields(record, "schema_version kind data gaps")
    require(type(record["schema_version"]) is int and record["schema_version"] == 1,
            "unsupported schema version")
    strings(record["gaps"])
    kind, data = record["kind"], record["data"]
    text(kind)
    if kind == "source-selection":
        fields(data, "package pin upstream archives")
        text(data["package"])
        pin = data["pin"]
        fields(pin, "month repository revision path digest")
        for key in ("repository", "path"):
            text(pin[key])
        revision(pin["revision"])
        digest(pin["digest"])
        text(pin["month"])
        try:
            day = date.fromisoformat(pin["month"])
        except ValueError:
            raise RecordError("invalid pin month") from None
        require(day.day == 1 and day.isoformat() == pin["month"], "pin month must be YYYY-MM-01")
        require(type(data["upstream"]) is list and bool(data["upstream"]), "missing upstream revisions")
        for upstream in data["upstream"]:
            fields(upstream, "repository revision")
            text(upstream["repository"])
            if upstream["revision"] is None:
                require(bool(record["gaps"]), "unknown upstream revision needs a gap")
            else:
                revision(upstream["revision"])
        artifacts(data["archives"], nonempty=True)
    elif kind == "build-inputs":
        fields(data, "package step purpose sources recipe patches target options environment materials dependencies")
        text(data["package"])
        text(data["step"])
        require(data["purpose"] in ("package", "assembly"), "invalid input purpose")
        refs(data["sources"], nonempty=data["purpose"] == "package")
        artifact(data["recipe"])
        artifacts(data["patches"])
        text(data["target"])
        for name in ("options", "environment"):
            require(type(data[name]) is dict, "expected string mapping")
            for key, value in data[name].items():
                text(key)
                require(type(value) is str, "expected string mapping value")
        require(set(data["environment"]) <= ENVIRONMENT, "environment key not allowlisted")
        artifacts(data["materials"], nonempty=True)
        output_bindings(data["dependencies"])
    elif kind == "attempt-start":
        fields(data, "attempt_id inputs prepared_at retry_of")
        text(data["attempt_id"])
        digest(data["inputs"])
        timestamp(data["prepared_at"])
        if data["retry_of"] is not None:
            digest(data["retry_of"])
    elif kind == "attempt-result":
        fields(data, "attempt outcome finished_at jobs traces outputs summary")
        digest(data["attempt"])
        require(data["outcome"] in ("succeeded", "failed", "cancelled", "uncertain"), "invalid outcome")
        timestamp(data["finished_at"])
        text(data["summary"])
        for name, keys in (("jobs", "host_id job_id"), ("traces", "host_id build_id")):
            require(type(data[name]) is list, "expected locator list")
            for locator in data[name]:
                fields(locator, keys)
                for value in locator.values():
                    text(value)
        refs(data["outputs"], nonempty=data["outcome"] == "succeeded")
        require(data["outcome"] == "succeeded" or not data["outputs"],
                "only successful results publish outputs")
    elif kind == "package-output":
        fields(data, "package attempt artifacts")
        text(data["package"])
        artifacts(data["artifacts"], nonempty=True)
        if data["attempt"] is None:
            require(bool(record["gaps"]), "legacy output must explain missing provenance")
        else:
            digest(data["attempt"])
    elif kind == "generation":
        fields(data, "generation_id assembly_result packages artifact content_manifest verification")
        text(data["generation_id"])
        digest(data["assembly_result"])
        output_bindings(data["packages"], nonempty=True)
        artifact(data["artifact"])
        artifact(data["content_manifest"])
        artifacts(data["verification"])
    elif kind == "source-repository":
        fields(data, "location normalization")
        text(data["location"])
        require(len(data["location"]) <= 4096 and
                not any(ord(c) < 32 for c in data["location"]),
                "invalid source repository location")
        require(data["normalization"] == "exact-literal-v1",
                "unsupported source repository normalization")
    elif kind == "source-reference":
        fields(data, "repository kind value")
        digest(data["repository"])
        require(data["kind"] in ("git", "tag", "opaque", "unknown"),
                "unsupported source reference kind")
        if data["kind"] == "git":
            revision(data["value"])
        elif data["kind"] in ("tag", "opaque"):
            text(data["value"])
            require(len(data["value"]) <= 256 and
                    not any(ord(c) < 32 for c in data["value"]),
                    "invalid source reference value")
        else:
            require(data["value"] is None, "unknown source reference must be null")
            require(bool(record["gaps"]), "unknown source reference needs a gap")
    elif kind == "source-archive":
        fields(data, "digest size")
        digest(data["digest"])
        require(type(data["size"]) is int and data["size"] >= 0,
                "invalid source archive size")
    elif kind == "source-archive-association":
        fields(data, "archive reference relationship producer")
        digest(data["archive"])
        digest(data["reference"])
        require(data["relationship"] == "declared-not-independently-reproduced",
                "unsupported source archive/reference relationship")
        producer = data["producer"]
        fields(producer, "name contract")
        text(producer["name"])
        text(producer["contract"])
    elif kind == "source-provenance":
        fields(data, "producer producer_observation package project output build_inputs source_selection archive associations")
        producer = data["producer"]
        fields(producer, "name contract")
        text(producer["name"])
        text(producer["contract"])
        digest(data["producer_observation"])
        text(data["package"])
        if data["project"] is not None:
            text(data["project"])
        for key in ("output", "build_inputs", "source_selection", "archive"):
            digest(data[key])
        refs(data["associations"], nonempty=True)
    elif kind == "generation-observation-snapshot":
        fields(data, "generation generation_id root_inventory_digest observations record_set_digest")
        digest(data["generation"])
        text(data["generation_id"])
        digest(data["root_inventory_digest"])
        observed = snapshot_record_set_digest(data["generation"], data["observations"])
        require(data["record_set_digest"] == observed,
                "generation observation snapshot record-set digest differs")
    elif kind == "verification-check":
        fields(data, "producer check_id definition_digest granularity")
        producer = data["producer"]
        fields(producer, "name contract")
        text(producer["name"])
        text(producer["contract"])
        text(data["check_id"])
        digest(data["definition_digest"])
        require(data["granularity"] == "command", "unsupported verification check granularity")
    elif kind == "observation-coverage":
        fields(data, "producer subject family collector scope outcome observation_count details")
        producer = data["producer"]
        fields(producer, "name contract")
        text(producer["name"])
        text(producer["contract"])
        subject = data["subject"]
        fields(subject, "kind generation_id root_inventory_digest")
        require(subject["kind"] == "generation-candidate", "unsupported coverage subject")
        text(subject["generation_id"])
        digest(subject["root_inventory_digest"])
        require(data["family"] in COVERAGE_FAMILIES, "unsupported coverage family")
        collector = data["collector"]
        fields(collector, "implementation_digest")
        digest(collector["implementation_digest"])
        require(type(data["scope"]) is dict, "coverage scope must be an object")
        canonical(data["scope"])
        require(data["outcome"] in COVERAGE_OUTCOMES, "unsupported coverage outcome")
        require(type(data["observation_count"]) is int and data["observation_count"] >= 0,
                "invalid coverage observation count")
        require(type(data["details"]) is dict, "coverage details must be an object")
        canonical(data["details"])
    elif kind == "relationship-observation":
        fields(data, "producer producer_observation subject relation target evidence")
        producer = data["producer"]
        fields(producer, "name contract")
        text(producer["name"])
        text(producer["contract"])
        digest(data["producer_observation"])
        relation = data["relation"]
        require(relation in RELATIONSHIPS, "unsupported relationship observation")
        subject, target, evidence = data["subject"], data["target"], data["evidence"]
        if relation in PACKAGE_RELATIONSHIPS:
            fields(subject, "kind package output_record")
            require(subject["kind"] == "package", "package relationship needs package subject")
            text(subject["package"])
            digest(subject["output_record"])
            if relation == "used-build-output":
                fields(target, "kind value package")
                require(target["kind"] == "package-output",
                        "used build output needs package-output target")
                digest(target["value"])
                text(target["package"])
                fields(evidence, "kind record")
                require(evidence["kind"] == "canonical-build-inputs",
                        "used build output needs canonical build-input evidence")
                digest(evidence["record"])
            else:
                fields(target, "kind value")
                require(target["kind"] == "package",
                        "declared dependency needs package target")
                text(target["value"])
                fields(evidence, "kind artifact")
                require(evidence["kind"] == "frozen-recipe",
                        "declared dependency needs frozen recipe evidence")
                artifact(evidence["artifact"])
        else:
            fields(subject, "kind path digest packages")
            require(subject["kind"] == "artifact", "artifact relationship needs artifact subject")
            text(subject["path"])
            require(subject["path"].startswith("/") and "\0" not in subject["path"],
                    "artifact subject path must be absolute")
            digest(subject["digest"])
            strings(subject["packages"])
            require(subject["packages"] == sorted(subject["packages"]),
                    "artifact subject packages must be sorted")
            if relation in ("needs-library", "provides-soname"):
                fields(target, "kind value")
                require(target["kind"] == "soname", "library relationship needs SONAME target")
                text(target["value"])
                fields(evidence, "kind tool")
                require(evidence["kind"] == "elf-metadata",
                        "ELF relationship needs elf-metadata evidence")
                fields(evidence["tool"], "name sha256")
                require(evidence["tool"]["name"] == "readelf",
                        "unsupported ELF metadata tool")
                require(isinstance(evidence["tool"]["sha256"], str) and
                        re.fullmatch(r"[0-9a-f]{64}", evidence["tool"]["sha256"]) is not None,
                        "invalid ELF metadata tool digest")
            elif relation == "elf-interpreter":
                fields(target, "kind value")
                require(target["kind"] == "path", "ELF interpreter needs path target")
                text(target["value"])
                require(target["value"].startswith("/") and "\0" not in target["value"],
                        "ELF interpreter path must be absolute")
                fields(evidence, "kind tool")
                require(evidence["kind"] == "elf-metadata",
                        "ELF interpreter needs elf-metadata evidence")
                fields(evidence["tool"], "name sha256")
                require(evidence["tool"]["name"] == "readelf",
                        "unsupported ELF metadata tool")
                require(isinstance(evidence["tool"]["sha256"], str) and
                        re.fullmatch(r"[0-9a-f]{64}", evidence["tool"]["sha256"]) is not None,
                        "invalid ELF metadata tool digest")
            else:
                fields(target, "kind value")
                require(target["kind"] == "path", "script interpreter needs path target")
                text(target["value"])
                require(target["value"].startswith("/") and "\0" not in target["value"],
                        "script interpreter path must be absolute")
                fields(evidence, "kind argument")
                require(evidence["kind"] == "shebang",
                        "script interpreter needs shebang evidence")
                if evidence["argument"] is not None:
                    text(evidence["argument"])
    elif kind == "verification-execution":
        fields(data, "producer producer_observation check_id definition_digest subject attempt_id sequence outcome execution environment_digest evidence granularity timing")
        producer = data["producer"]
        fields(producer, "name contract")
        text(producer["name"])
        text(producer["contract"])
        digest(data["producer_observation"])
        text(data["check_id"])
        digest(data["definition_digest"])
        subject = data["subject"]
        fields(subject, "kind generation_id root_inventory_digest")
        require(subject["kind"] == "generation-candidate", "unsupported verification subject")
        text(subject["generation_id"])
        digest(subject["root_inventory_digest"])
        text(data["attempt_id"])
        require(type(data["sequence"]) is int and data["sequence"] >= 0,
                "invalid verification sequence")
        require(data["outcome"] in ("PASS", "FAIL", "ERROR", "SKIP"),
                "invalid verification outcome")
        require(type(data["execution"]) is dict, "verification execution must be an object")
        canonical(data["execution"])
        digest(data["environment_digest"])
        require(type(data["evidence"]) is list and bool(data["evidence"]),
                "verification evidence must be a nonempty list")
        for item in data["evidence"]:
            require(type(item) is dict, "verification evidence entry must be an object")
            canonical(item)
        require(data["granularity"] == "command", "unsupported verification granularity")
        timing = data["timing"]
        fields(timing, "started_at finished_at observed_at")
        parsed = {}
        for key in ("started_at", "finished_at", "observed_at"):
            parsed[key] = None if timing[key] is None else observation_timestamp(timing[key])
        if parsed["started_at"] is not None and parsed["finished_at"] is not None:
            require(parsed["finished_at"] >= parsed["started_at"],
                    "verification execution predates its start")
    else:
        raise RecordError("unsupported record kind")


def make_record(kind: str, data: dict, *, gaps: list[str] | None = None) -> Record:
    record = {"schema_version": 1, "kind": kind, "data": data, "gaps": gaps or []}
    validate(record)
    # Detach from mutable caller-owned inputs.
    return loads(canonical(record))


def record_id(record: Record) -> str:
    validate(record)
    return "sha256:" + hashlib.sha256(canonical(record)).hexdigest()


def references(record: Record) -> list[tuple[str, str]]:
    """Return typed graph edges; artifact hashes are not record references."""
    validate(record)
    data, kind = record["data"], record["kind"]
    if kind == "generation-observation-snapshot":
        result = [(data["generation"], "generation")]
        for group, expected in SNAPSHOT_GROUPS.items():
            result.extend((identity, expected) for identity in data["observations"][group])
        return result
    if kind == "relationship-observation":
        if data["relation"] not in PACKAGE_RELATIONSHIPS:
            return []
        result = [(data["subject"]["output_record"], "package-output")]
        if data["relation"] == "used-build-output":
            result += [(data["target"]["value"], "package-output"),
                       (data["evidence"]["record"], "build-inputs")]
        return result
    if kind == "source-reference":
        return [(data["repository"], "source-repository")]
    if kind == "source-archive-association":
        return [(data["archive"], "source-archive"),
                (data["reference"], "source-reference")]
    if kind == "source-provenance":
        return [(data["output"], "package-output"),
                (data["build_inputs"], "build-inputs"),
                (data["source_selection"], "source-selection"),
                (data["archive"], "source-archive")] + [
                    (identity, "source-archive-association")
                    for identity in data["associations"]]
    if kind == "build-inputs":
        return [(x, "source-selection") for x in data["sources"]] + [(item[key], expected) for item in data["dependencies"]
                for key, expected in (("output", "package-output"), ("result", "attempt-result")) if item[key]]
    if kind == "attempt-start":
        return [(data["inputs"], "build-inputs")] + ([(data["retry_of"], "attempt-result")] if data["retry_of"] else [])
    if kind == "attempt-result":
        return [(data["attempt"], "attempt-start")] + [(x, "package-output") for x in data["outputs"]]
    if kind == "package-output":
        return [(data["attempt"], "attempt-start")] if data["attempt"] else []
    if kind == "generation":
        return [(data["assembly_result"], "attempt-result")] + [
            (item[key], expected) for item in data["packages"]
            for key, expected in (("output", "package-output"), ("result", "attempt-result")) if item[key]]
    return []


def artifact_references(record: Record) -> list[dict]:
    data, kind = record["data"], record["kind"]
    if kind == "relationship-observation" and data["relation"].startswith("declares-"):
        return [data["evidence"]["artifact"]]
    if kind == "source-selection":
        return data["archives"] + [{"name": "commit-pin.py", "digest": data["pin"]["digest"], "size": None}]
    if kind == "source-archive":
        return [{"name": "source-archive", "digest": data["digest"], "size": data["size"]}]
    if kind == "build-inputs":
        return [data["recipe"]] + data["patches"] + data["materials"]
    if kind == "package-output":
        return data["artifacts"]
    if kind == "generation":
        return [data["artifact"], data["content_manifest"]] + data["verification"]
    return []
