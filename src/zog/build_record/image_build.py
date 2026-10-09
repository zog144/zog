"""Strict adapters for image-build integration observation producer contracts."""
from __future__ import annotations

import hashlib
from typing import Any

from .graph import inspect, validate_bundle
from .model import (MAX_BUNDLE_BYTES, artifact, canonical, digest, fields, make_record,
                    record_id, require, revision, text)
from .snapshot import generation_observation_snapshot

GENERATION_SCHEMA = "image-build-integration-observations-v1"
CANDIDATE_SCHEMA = "image-build-candidate-verifications-v1"
VERIFICATION_SCHEMA = "image-build-verification-observation-v1"
RELATIONS = frozenset({
    "needs-library", "provides-soname", "elf-interpreter", "script-interpreter",
    "declares-build-dependency", "declares-test-dependency",
    "declares-runtime-dependency", "used-build-output",
})


def _bounded(value: Any) -> None:
    require(len(canonical(value)) <= MAX_BUNDLE_BYTES, "image-build observation envelope byte limit exceeded")


def _object(value: Any, message: str) -> None:
    require(type(value) is dict, message)
    canonical(value)


def _objects(value: Any, message: str) -> None:
    require(type(value) is list, message)
    for item in value:
        _object(item, message)


def _producer_identity(value: dict, label: str) -> None:
    digest(value["id"])
    payload = {key: child for key, child in value.items() if key != "id"}
    observed = "sha256:" + hashlib.sha256(canonical(payload)).hexdigest()
    require(value["id"] == observed, label + " identity differs")


def _verification(value: Any) -> None:
    fields(value, "schema id check_id definition_digest subject attempt_id sequence outcome execution environment_digest evidence granularity timing producer")
    require(value["schema"] == VERIFICATION_SCHEMA, "unsupported image-build verification schema")
    _producer_identity(value, "image-build verification observation")
    text(value["check_id"])
    digest(value["definition_digest"])
    subject = value["subject"]
    fields(subject, "kind generation_id root_inventory_digest")
    require(subject["kind"] == "generation-candidate", "unsupported image-build verification subject")
    text(subject["generation_id"])
    digest(subject["root_inventory_digest"])
    text(value["attempt_id"])
    require(type(value["sequence"]) is int and value["sequence"] >= 0,
            "invalid image-build verification sequence")
    require(value["outcome"] in ("PASS", "FAIL", "ERROR", "SKIP"),
            "invalid image-build verification outcome")
    _object(value["execution"], "image-build execution must be an object")
    digest(value["environment_digest"])
    require(type(value["evidence"]) is list and bool(value["evidence"]),
            "image-build verification evidence must be nonempty")
    for evidence in value["evidence"]:
        _object(evidence, "image-build verification evidence entry must be an object")
    require(value["granularity"] == "command", "unsupported image-build verification granularity")
    timing = value["timing"]
    fields(timing, "started_at finished_at observed_at")
    for key in ("started_at", "finished_at", "observed_at"):
        if timing[key] is not None:
            text(timing[key])
    producer = value["producer"]
    fields(producer, "name contract")
    require(producer["name"] == "image-build" and producer["contract"] == VERIFICATION_SCHEMA,
            "image-build verification producer differs")


CHECK_PRODUCER = {"name": "image-build", "contract": VERIFICATION_SCHEMA}


def _check(value: Any) -> None:
    fields(value, "check_id definition_digest granularity")
    text(value["check_id"])
    digest(value["definition_digest"])
    require(value["granularity"] == "command", "unsupported image-build check granularity")


def verification_check(value: dict) -> dict:
    """Canonical logical-check definition, independent of a generation or execution."""
    _check(value)
    return make_record("verification-check", {
        "producer": CHECK_PRODUCER,
        "check_id": value["check_id"],
        "definition_digest": value["definition_digest"],
        "granularity": value["granularity"],
    })


def verification_check_from_execution(value: dict) -> dict:
    _verification(value)
    return verification_check({
        "check_id": value["check_id"],
        "definition_digest": value["definition_digest"],
        "granularity": value["granularity"],
    })


def _relationship_record(value: dict) -> dict:
    return make_record("relationship-observation", {
        "producer": GENERATION_PRODUCER,
        "producer_observation": value["id"],
        "subject": value["subject"],
        "relation": value["relation"],
        "target": value["target"],
        "evidence": value["evidence"],
    })


def _relationship(value: Any) -> None:
    fields(value, "id subject relation target evidence")
    require(value["relation"] in RELATIONS, "unsupported image-build relationship")
    _object(value["subject"], "image-build relationship subject must be an object")
    _object(value["target"], "image-build relationship target must be an object")
    _object(value["evidence"], "image-build relationship evidence must be an object")
    _producer_identity(value, "image-build relationship")
    _relationship_record(value)


def _source(value: Any) -> None:
    fields(value, "id package project output_record build_inputs_record source_selection_record pin archive downloads upstream archive_revision_relationship release_tags gaps")
    _producer_identity(value, "image-build source observation")
    text(value["package"])
    if value["project"] is not None:
        text(value["project"])
    for key in ("output_record", "build_inputs_record", "source_selection_record"):
        digest(value[key])
    _object(value["pin"], "image-build source pin must be an object")
    artifact(value["archive"])
    _objects(value["downloads"], "image-build downloads must be object entries")
    require(type(value["upstream"]) is list and bool(value["upstream"]),
            "image-build upstream declarations must be nonempty")
    repositories = set()
    expected_tags = []
    for upstream in value["upstream"]:
        fields(upstream, "repository revision revision_type")
        repository = upstream["repository"]
        text(repository)
        require(len(repository) <= 4096 and not any(ord(c) < 32 for c in repository),
                "invalid image-build upstream repository")
        require(repository not in repositories, "duplicate image-build upstream repository")
        repositories.add(repository)
        kind = upstream["revision_type"]
        require(kind in ("git", "tag", "opaque", "unknown"),
                "unsupported image-build upstream revision type")
        if kind == "git":
            revision(upstream["revision"])
        elif kind in ("tag", "opaque"):
            text(upstream["revision"])
            require(len(upstream["revision"]) <= 256 and
                    not any(ord(c) < 32 for c in upstream["revision"]),
                    "invalid image-build upstream reference")
            if kind == "tag":
                expected_tags.append({"repository": repository, "tag": upstream["revision"]})
        else:
            require(upstream["revision"] is None,
                    "unknown image-build upstream revision must be null")
    require(value["archive_revision_relationship"] == "declared-not-independently-reproduced",
            "unsupported archive/revision relationship")
    require(type(value["release_tags"]) is list, "image-build release tags must be a list")
    for tag in value["release_tags"]:
        fields(tag, "repository tag")
        text(tag["repository"])
        text(tag["tag"])
    require(value["release_tags"] == expected_tags,
            "image-build release tag projection differs from upstream declarations")
    require(type(value["gaps"]) is list, "image-build source gaps must be a list")
    seen_gaps = set()
    for gap in value["gaps"]:
        text(gap)
        require(gap not in seen_gaps, "duplicate image-build source gap")
        seen_gaps.add(gap)
    if any(upstream["revision_type"] == "unknown" for upstream in value["upstream"]):
        require(bool(value["gaps"]), "unknown image-build upstream reference needs a gap")


GENERATION_PRODUCER = {"name": "image-build", "contract": GENERATION_SCHEMA}


def relationship_observation(value: dict) -> dict:
    """Canonicalize one strictly validated image-build relationship observation."""
    _relationship(value)
    return _relationship_record(value)


def source_provenance_records(value: dict) -> list[dict]:
    """Canonical source-development facts for one validated image-build source row."""
    _source(value)
    records = []
    repositories = {}
    references = []
    for upstream in value["upstream"]:
        repository = make_record("source-repository", {
            "location": upstream["repository"], "normalization": "exact-literal-v1"})
        repository_id = record_id(repository)
        if repository_id not in repositories:
            repositories[repository_id] = repository
            records.append(repository)
        gaps = (["Upstream source reference is explicitly unknown."]
                if upstream["revision_type"] == "unknown" else [])
        reference = make_record("source-reference", {
            "repository": repository_id, "kind": upstream["revision_type"],
            "value": upstream["revision"]}, gaps=gaps)
        records.append(reference)
        references.append(record_id(reference))
    archive = make_record("source-archive", {
        "digest": value["archive"]["digest"], "size": value["archive"]["size"]})
    archive_id = record_id(archive)
    records.append(archive)
    associations = []
    for reference_id in references:
        association = make_record("source-archive-association", {
            "archive": archive_id, "reference": reference_id,
            "relationship": value["archive_revision_relationship"],
            "producer": GENERATION_PRODUCER})
        records.append(association)
        associations.append(record_id(association))
    provenance = make_record("source-provenance", {
        "producer": GENERATION_PRODUCER, "producer_observation": value["id"],
        "package": value["package"], "project": value["project"],
        "output": value["output_record"], "build_inputs": value["build_inputs_record"],
        "source_selection": value["source_selection_record"], "archive": archive_id,
        "associations": associations}, gaps=value["gaps"])
    records.append(provenance)
    return records


def verification_execution(value: dict) -> dict:
    """Convert one validated producer observation to an immutable canonical record.

    Publication state is deliberately absent. A candidate observation therefore has
    the same build-record identity before and after its generation is published.
    """
    _verification(value)
    return make_record("verification-execution", {
        "producer": value["producer"],
        "producer_observation": value["id"],
        "check_id": value["check_id"],
        "definition_digest": value["definition_digest"],
        "subject": value["subject"],
        "attempt_id": value["attempt_id"],
        "sequence": value["sequence"],
        "outcome": value["outcome"],
        "execution": value["execution"],
        "environment_digest": value["environment_digest"],
        "evidence": value["evidence"],
        "granularity": value["granularity"],
        "timing": value["timing"],
    })


def validate_image_build_candidate(value: Any) -> None:
    _bounded(value)
    fields(value, "schema generation_id results coverage")
    require(value["schema"] == CANDIDATE_SCHEMA, "unsupported image-build candidate schema")
    text(value["generation_id"])
    text(value["coverage"])
    require(type(value["results"]) is list, "image-build candidate results must be a list")
    seen = set()
    for result in value["results"]:
        _verification(result)
        require(result["id"] not in seen, "duplicate image-build verification observation")
        seen.add(result["id"])
        require(result["subject"]["generation_id"] == value["generation_id"],
                "candidate verification generation differs")


def validate_image_build_generation(value: Any, bundle: dict) -> None:
    """Validate a published observation envelope against its canonical generation closure."""
    _bounded(value)
    fields(value, "schema id producer context verification relationships sources coverage gaps derivation")
    require(value["schema"] == GENERATION_SCHEMA, "unsupported image-build generation observation schema")
    _producer_identity(value, "image-build generation observation")
    producer = value["producer"]
    fields(producer, "name contract implementation_digest")
    require(producer["name"] == "image-build" and producer["contract"] == GENERATION_SCHEMA,
            "image-build generation producer differs")
    digest(producer["implementation_digest"])

    context = value["context"]
    fields(context, "generation_id generation_record root_inventory_digest")
    text(context["generation_id"])
    digest(context["generation_record"])
    digest(context["root_inventory_digest"])

    validate_bundle(bundle)
    report = inspect(bundle)
    require(not report["missing_records"], "image-build generation bundle is incomplete")
    require(context["generation_record"] in bundle["roots"],
            "image-build generation record is not an export root")
    generation = bundle["records"].get(context["generation_record"])
    require(generation is not None and generation["kind"] == "generation",
            "image-build generation context does not reference a canonical generation")
    require(record_id(generation) == context["generation_record"],
            "image-build generation record identity differs")
    require(generation["data"]["generation_id"] == context["generation_id"],
            "image-build owner generation identity differs")
    records = bundle["records"]

    verification = value["verification"]
    fields(verification, "checks results coverage")
    require(type(verification["checks"]) is list, "image-build checks must be a list")
    for check in verification["checks"]:
        _check(check)
    text(verification["coverage"])
    require(type(verification["results"]) is list, "image-build verification results must be a list")
    seen = set()
    for result in verification["results"]:
        _verification(result)
        require(result["id"] not in seen, "duplicate image-build verification observation")
        seen.add(result["id"])
        require(result["subject"]["generation_id"] == context["generation_id"],
                "published verification generation differs")
        require(result["subject"]["root_inventory_digest"] == context["root_inventory_digest"],
                "published verification root inventory differs")

    require(type(value["relationships"]) is list, "image-build relationships must be a list")
    relation_ids = set()
    generation_packages = {
        records[item["output"]]["data"]["package"]: item["output"]
        for item in generation["data"]["packages"]
    }
    for relationship in value["relationships"]:
        _relationship(relationship)
        require(relationship["id"] not in relation_ids, "duplicate image-build relationship")
        relation_ids.add(relationship["id"])
        subject = relationship["subject"]
        if subject["kind"] == "package":
            output = records.get(subject["output_record"])
            require(output is not None and output["kind"] == "package-output",
                    "image-build relationship package output is unavailable")
            require(output["data"]["package"] == subject["package"],
                    "image-build relationship subject package differs")
            require(generation_packages.get(subject["package"]) == subject["output_record"],
                    "image-build relationship subject is not the installed package output")
            require(output["data"]["attempt"] is not None,
                    "image-build relationship cannot bind a legacy package output")
            start = records.get(output["data"]["attempt"])
            require(start is not None and start["kind"] == "attempt-start",
                    "image-build relationship package attempt is unavailable")
            if relationship["relation"] == "used-build-output":
                require(relationship["evidence"]["record"] == start["data"]["inputs"],
                        "image-build used-output evidence differs from canonical inputs")
                inputs = records.get(start["data"]["inputs"])
                require(inputs is not None and inputs["kind"] == "build-inputs",
                        "image-build used-output build inputs are unavailable")
                target = records.get(relationship["target"]["value"])
                require(target is not None and target["kind"] == "package-output",
                        "image-build used-output target is unavailable")
                require(target["data"]["package"] == relationship["target"]["package"],
                        "image-build used-output target package differs")
                require(any(item["output"] == relationship["target"]["value"]
                            for item in inputs["data"]["dependencies"]),
                        "image-build used-output target is not a canonical dependency")
        else:
            installed = set(generation_packages)
            require(set(subject["packages"]) <= installed,
                    "image-build artifact owner is not an installed generation package")

    require(type(value["sources"]) is list, "image-build sources must be a list")
    source_ids = set()
    for source in value["sources"]:
        _source(source)
        require(source["id"] not in source_ids, "duplicate image-build source observation")
        source_ids.add(source["id"])
        expected = (("output_record", "package-output"),
                    ("build_inputs_record", "build-inputs"),
                    ("source_selection_record", "source-selection"))
        for key, kind in expected:
            referenced = records.get(source[key])
            require(referenced is not None and referenced["kind"] == kind,
                    "image-build source observation canonical reference differs")
        output_record = records[source["output_record"]]
        inputs_record = records[source["build_inputs_record"]]
        selected_record = records[source["source_selection_record"]]
        output = output_record["data"]
        inputs = inputs_record["data"]
        selected = selected_record["data"]
        require(output["package"] == source["package"], "image-build source package differs")
        require(inputs["package"] == source["package"], "image-build source input package differs")
        require(selected["package"] == source["package"], "image-build source selection package differs")
        require(source["source_selection_record"] in inputs["sources"],
                "image-build source selection is not a frozen build input")
        require(source["pin"] == selected["pin"], "image-build source pin differs from canonical selection")
        require(source["archive"] in selected["archives"],
                "image-build source archive differs from canonical selection")
        require(output["attempt"] is not None, "image-build source observation cannot bind a legacy output")
        start = records.get(output["attempt"])
        require(start is not None and start["kind"] == "attempt-start",
                "image-build source output attempt is unavailable")
        require(start["data"]["inputs"] == source["build_inputs_record"],
                "image-build source build-input binding differs")

    coverage = value["coverage"]
    fields(coverage, "elf_files script_files readelf symlinks resolution unsupported")
    require(type(coverage["elf_files"]) is int and coverage["elf_files"] >= 0,
            "invalid image-build ELF coverage count")
    require(type(coverage["script_files"]) is int and coverage["script_files"] >= 0,
            "invalid image-build script coverage count")
    if coverage["readelf"] is not None:
        fields(coverage["readelf"], "name sha256")
        require(coverage["readelf"]["name"] == "readelf",
                "unsupported image-build ELF collector")
        require(isinstance(coverage["readelf"]["sha256"], str) and
                len(coverage["readelf"]["sha256"]) == 64 and
                all(c in "0123456789abcdef" for c in coverage["readelf"]["sha256"]),
                "invalid image-build readelf digest")
    require(coverage["symlinks"] == "not-followed",
            "unsupported image-build symlink coverage")
    require(coverage["resolution"] == "interfaces-only",
            "unsupported image-build relationship resolution scope")
    require(type(coverage["unsupported"]) is list, "image-build unsupported coverage must be a list")
    for item in coverage["unsupported"]:
        text(item)
    require(len(coverage["unsupported"]) == len(set(coverage["unsupported"])),
            "duplicate image-build unsupported coverage entry")
    _objects(value["gaps"], "image-build gaps must be object entries")
    text(value["derivation"])


def _coverage_subject(value: dict) -> dict:
    return {
        "kind": "generation-candidate",
        "generation_id": value["context"]["generation_id"],
        "root_inventory_digest": value["context"]["root_inventory_digest"],
    }


def _coverage_record(value: dict, family: str, scope: dict, outcome: str,
                     observation_count: int, details: dict) -> dict:
    return make_record("observation-coverage", {
        "producer": GENERATION_PRODUCER,
        "subject": _coverage_subject(value),
        "family": family,
        "collector": {"implementation_digest": value["producer"]["implementation_digest"]},
        "scope": scope,
        "outcome": outcome,
        "observation_count": observation_count,
        "details": details,
    })


def image_build_coverage_records(value: dict) -> list[dict]:
    """Translate image-build v1 declared scope and explicit gaps into canonical coverage."""
    coverage = value["coverage"]
    gaps = value["gaps"]
    relations = value["relationships"]

    verification_missing = any(
        gap.get("reason") == "no-canonical-named-verification-report"
        for gap in gaps)
    verification_definitions = {
        (item["check_id"], item["definition_digest"], item["granularity"])
        for item in value["verification"]["checks"]
    } | {
        (item["check_id"], item["definition_digest"], item["granularity"])
        for item in value["verification"]["results"]
    }
    verification_outcome = (
        "unavailable"
        if verification_missing and not verification_definitions
           and not value["verification"]["results"]
        else "partial")
    verification = _coverage_record(
        value, "verification-commands",
        {"selection": "named-installed-checks", "granularity": "command"},
        verification_outcome,
        len(value["verification"]["results"]),
        {
            "declared_coverage": value["verification"]["coverage"],
            "check_count": len(verification_definitions),
            "canonical_named_report_available": not verification_missing,
            "exclusions": ["upstream-subtests", "anonymous-legacy-jobs"],
        })

    elf_issues = [gap for gap in gaps if gap.get("reason") in (
        "readelf-unavailable", "readelf-timeout", "elf-inspection-failed-or-too-large")]
    if coverage["elf_files"] and coverage["readelf"] is None:
        elf_outcome = "unavailable"
    elif elf_issues:
        elf_outcome = "partial"
    else:
        elf_outcome = "complete"
    elf_count = sum(1 for item in relations
                    if item["relation"] in ("needs-library", "provides-soname", "elf-interpreter"))
    elf = _coverage_record(
        value, "elf-interfaces",
        {
            "files": "installed-regular-elf",
            "relations": ["needs-library", "provides-soname", "elf-interpreter"],
            "symlinks": coverage["symlinks"],
            "resolution": coverage["resolution"],
        },
        elf_outcome, elf_count,
        {
            "file_count": coverage["elf_files"],
            "readelf": coverage["readelf"],
            "issues": elf_issues,
            "unsupported": coverage["unsupported"],
        })

    script_issues = [gap for gap in gaps if gap.get("reason") in (
        "unsupported-shebang", "non-utf8-shebang", "non-absolute-shebang")]
    script_count = sum(1 for item in relations if item["relation"] == "script-interpreter")
    scripts = _coverage_record(
        value, "script-interpreters",
        {
            "files": "installed-regular-scripts",
            "relations": ["script-interpreter"],
            "symlinks": coverage["symlinks"],
            "resolution": coverage["resolution"],
        },
        "partial" if script_issues else "complete", script_count,
        {
            "file_count": coverage["script_files"],
            "issues": script_issues,
            "unsupported": [item for item in coverage["unsupported"]
                            if item == "env-PATH-resolution"],
        })

    package_gaps = [gap for gap in gaps if gap.get("reason") in (
        "legacy-output-without-source-or-recipe", "no-frozen-dependency-declaration")]
    declaration_count = sum(1 for item in relations if item["relation"] in (
        "declares-build-dependency", "declares-test-dependency",
        "declares-runtime-dependency"))
    declarations = _coverage_record(
        value, "declared-package-dependencies",
        {
            "packages": "installed-with-frozen-recipe",
            "relations": ["declares-build-dependency", "declares-test-dependency",
                          "declares-runtime-dependency"],
        },
        "partial" if package_gaps else "complete", declaration_count,
        {"issues": package_gaps})

    used_gaps = [gap for gap in gaps if gap.get("reason") == "legacy-output-without-source-or-recipe"]
    used_count = sum(1 for item in relations if item["relation"] == "used-build-output")
    used = _coverage_record(
        value, "used-build-output",
        {"packages": "installed-with-canonical-build-inputs",
         "relations": ["used-build-output"]},
        "partial" if used_gaps else "complete", used_count,
        {"issues": used_gaps})

    source_gaps = [gap for gap in gaps if gap.get("reason") == "legacy-output-without-source-or-recipe"]
    sources = _coverage_record(
        value, "source-provenance",
        {"packages": "installed-with-canonical-source-inputs"},
        "partial" if source_gaps else "complete", len(value["sources"]),
        {"issues": source_gaps})

    return [verification, elf, scripts, declarations, used, sources]


def ingest_image_build_checks(value: dict, bundle: dict) -> list[dict]:
    """Canonicalize distinct definitions declared or executed in a generation export."""
    validate_image_build_generation(value, bundle)
    result = []
    seen = set()
    definitions = list(value["verification"]["checks"]) + [{
        "check_id": execution["check_id"],
        "definition_digest": execution["definition_digest"],
        "granularity": execution["granularity"],
    } for execution in value["verification"]["results"]]
    for definition in definitions:
        record = verification_check(definition)
        identity = record_id(record)
        if identity not in seen:
            seen.add(identity)
            result.append(record)
    return result


def ingest_image_build_candidate_checks(value: dict) -> list[dict]:
    """Canonicalize check definitions carried by candidate terminal observations."""
    validate_image_build_candidate(value)
    result = []
    seen = set()
    for execution in value["results"]:
        record = verification_check_from_execution(execution)
        identity = record_id(record)
        if identity not in seen:
            seen.add(identity)
            result.append(record)
    return result


def ingest_image_build_coverage(value: dict, bundle: dict) -> list[dict]:
    """Canonicalize explicit collection coverage for a published generation."""
    validate_image_build_generation(value, bundle)
    return image_build_coverage_records(value)


def _dedupe_records(records: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for record in records:
        identity = record_id(record)
        if identity not in seen:
            seen.add(identity)
            result.append(record)
    return result


def ingest_image_build_snapshot(value: dict, bundle: dict) -> list[dict]:
    """Construct dependency-first canonical records, with the snapshot last.

    This function validates and constructs immutable records only. It does not persist
    them or publish/select the snapshot. Image-build owns Store.put ordering, durable
    owner-state binding of the returned snapshot ID, and idempotent publication
    recovery after interruption.
    """
    validate_image_build_generation(value, bundle)

    checks = []
    definitions = list(value["verification"]["checks"]) + [{
        "check_id": execution["check_id"],
        "definition_digest": execution["definition_digest"],
        "granularity": execution["granularity"],
    } for execution in value["verification"]["results"]]
    for definition in definitions:
        checks.append(verification_check(definition))
    checks = _dedupe_records(checks)

    executions = _dedupe_records([
        verification_execution(item) for item in value["verification"]["results"]])
    relationships = _dedupe_records([
        relationship_observation(item) for item in value["relationships"]])

    source_records = []
    source_roots = []
    for item in value["sources"]:
        records = source_provenance_records(item)
        source_records.extend(records)
        source_roots.append(record_id(records[-1]))
    source_records = _dedupe_records(source_records)
    source_roots = sorted(set(source_roots))

    coverage = _dedupe_records(image_build_coverage_records(value))
    snapshot = generation_observation_snapshot(
        value["context"]["generation_record"],
        value["context"]["generation_id"],
        value["context"]["root_inventory_digest"],
        verification_checks=[record_id(item) for item in checks],
        verification_executions=[record_id(item) for item in executions],
        relationships=[record_id(item) for item in relationships],
        source_provenance=source_roots,
        coverage=[record_id(item) for item in coverage],
    )

    return _dedupe_records(
        source_records + checks + executions + relationships + coverage + [snapshot])


def ingest_image_build_relationships(value: dict, bundle: dict) -> list[dict]:
    """Canonicalize typed relationship observations after generation-envelope validation."""
    validate_image_build_generation(value, bundle)
    result = []
    seen = set()
    for relationship in value["relationships"]:
        record = relationship_observation(relationship)
        identity = record_id(record)
        if identity not in seen:
            seen.add(identity)
            result.append(record)
    return result


def ingest_image_build_sources(value: dict, bundle: dict) -> list[dict]:
    """Canonicalize source-development records after generation-envelope validation."""
    validate_image_build_generation(value, bundle)
    result = []
    seen = set()
    for source in value["sources"]:
        for record in source_provenance_records(source):
            identity = record_id(record)
            if identity not in seen:
                seen.add(identity)
                result.append(record)
    return result


def ingest_image_build_candidate(value: dict) -> list[dict]:
    """Canonicalize terminal observations for a candidate, published or not."""
    validate_image_build_candidate(value)
    return [verification_execution(result) for result in value["results"]]


def ingest_image_build_generation(value: dict, bundle: dict) -> list[dict]:
    """Canonicalize verification observations after binding the envelope to a generation."""
    validate_image_build_generation(value, bundle)
    return [verification_execution(result) for result in value["verification"]["results"]]
