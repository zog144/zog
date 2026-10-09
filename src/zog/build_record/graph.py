"""Bounded graph inspection; no execution, network retrieval or inferred history."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .model import (MAX_BUNDLE_BYTES, MAX_RECORDS, RecordError, artifact_references,
                    canonical, digest, fields, record_id, references, require, refs, timestamp)


def validate_bundle(bundle: dict) -> None:
    fields(bundle, "schema_version roots records")
    require(type(bundle["schema_version"]) is int and bundle["schema_version"] == 1,
            "unsupported bundle schema")
    refs(bundle["roots"], nonempty=True)
    require(type(bundle["records"]) is dict and len(bundle["records"]) <= MAX_RECORDS,
            "record count limit exceeded")
    require(len(canonical(bundle)) <= MAX_BUNDLE_BYTES, "bundle byte limit exceeded")
    for identity, record in bundle["records"].items():
        digest(identity)
        require(record_id(record) == identity, "record digest mismatch")


def inspect(bundle: dict) -> dict:
    """Missing edges are reported; wrong types or inconsistent facts are errors."""
    validate_bundle(bundle)
    records = bundle["records"]
    missing, visited, stack = set(), set(), list(bundle["roots"])
    while stack:
        identity = stack.pop()
        if identity in visited or identity in missing:
            continue
        if identity not in records:
            missing.add(identity)
            continue
        visited.add(identity)
        for target, expected in references(records[identity]):
            if target in records:
                require(records[target]["kind"] == expected, "record reference has wrong kind")
            stack.append(target)

    def get(identity):
        return records[identity]["data"] if identity in visited else None

    def check_bindings(bindings):
        packages = set()
        for item in bindings:
            output, result = get(item["output"]), get(item["result"])
            if output:
                require(output["package"] not in packages, "duplicate package identity")
                packages.add(output["package"])
                require((output["attempt"] is None) == (item["result"] is None),
                        "legacy/result binding mismatch")
                if result:
                    require(result["outcome"] == "succeeded" and item["output"] in result["outputs"]
                            and result["attempt"] == output["attempt"], "package result mismatch")

    attempts, results, generations = {}, {}, {}
    for identity in sorted(visited):
        record = records[identity]
        data, kind = record["data"], record["kind"]
        if kind == "generation-observation-snapshot":
            generation = get(data["generation"])
            if generation:
                require(generation["generation_id"] == data["generation_id"],
                        "snapshot owner generation identity differs")
                installed = {item["output"]: records[item["output"]]["data"]["package"]
                             for item in generation["packages"]
                             if item["output"] in records}
                installed_packages = set(installed.values())
                definitions = set()
                for identity in data["observations"]["verification_checks"]:
                    check = get(identity)
                    if check:
                        definitions.add((check["check_id"], check["definition_digest"],
                                         check["granularity"]))
                for identity in data["observations"]["verification_executions"]:
                    execution = get(identity)
                    if execution:
                        subject = execution["subject"]
                        require(subject["generation_id"] == data["generation_id"] and
                                subject["root_inventory_digest"] == data["root_inventory_digest"],
                                "snapshot verification execution subject differs")
                        require((execution["check_id"], execution["definition_digest"],
                                 execution["granularity"]) in definitions,
                                "snapshot execution lacks included check definition")
                for identity in data["observations"]["coverage"]:
                    coverage = get(identity)
                    if coverage:
                        subject = coverage["subject"]
                        require(subject["generation_id"] == data["generation_id"] and
                                subject["root_inventory_digest"] == data["root_inventory_digest"],
                                "snapshot coverage subject differs")
                for identity in data["observations"]["source_provenance"]:
                    source = get(identity)
                    if source:
                        require(source["output"] in installed,
                                "snapshot source provenance output is not installed")
                        require(installed[source["output"]] == source["package"],
                                "snapshot source provenance package differs")
                for identity in data["observations"]["relationships"]:
                    relation = get(identity)
                    if relation:
                        subject = relation["subject"]
                        if subject["kind"] == "package":
                            require(subject["output_record"] in installed,
                                    "snapshot relationship package output is not installed")
                            require(installed[subject["output_record"]] == subject["package"],
                                    "snapshot relationship package differs")
                        else:
                            require(set(subject["packages"]) <= installed_packages,
                                    "snapshot artifact owner is not installed")
        elif kind == "relationship-observation":
            relation = data["relation"]
            if relation in ("declares-build-dependency", "declares-test-dependency",
                            "declares-runtime-dependency", "used-build-output"):
                subject = data["subject"]
                output = get(subject["output_record"])
                if output:
                    require(output["package"] == subject["package"],
                            "relationship subject output package differs")
                    require(output["attempt"] is not None,
                            "package relationship cannot bind a legacy output")
                    start = get(output["attempt"])
                    inputs = get(start["inputs"]) if start else None
                    if relation == "used-build-output" and inputs:
                        require(data["evidence"]["record"] == start["inputs"],
                                "used output evidence is not the subject's build inputs")
                        target = get(data["target"]["value"])
                        if target:
                            require(target["package"] == data["target"]["package"],
                                    "used output target package differs")
                        require(any(item["output"] == data["target"]["value"]
                                    for item in inputs["dependencies"]),
                                "used output is not a canonical build-input dependency")
        elif kind == "source-reference":
            repository = get(data["repository"])
            if repository:
                require(repository["normalization"] == "exact-literal-v1",
                        "source reference repository normalization differs")
        elif kind == "source-archive-association":
            archive = get(data["archive"])
            reference = get(data["reference"])
            if archive and reference:
                require(data["relationship"] == "declared-not-independently-reproduced",
                        "source association semantics differ")
        elif kind == "source-provenance":
            output = get(data["output"])
            inputs = get(data["build_inputs"])
            selected = get(data["source_selection"])
            archive = get(data["archive"])
            if output:
                require(output["package"] == data["package"],
                        "source provenance output package differs")
                if output["attempt"] is not None:
                    start = get(output["attempt"])
                    if start:
                        require(start["inputs"] == data["build_inputs"],
                                "source provenance output inputs differ")
            if inputs:
                require(inputs["package"] == data["package"],
                        "source provenance build-input package differs")
                require(data["source_selection"] in inputs["sources"],
                        "source provenance selection is not a build input")
            if selected:
                require(selected["package"] == data["package"],
                        "source provenance selection package differs")
            if selected and archive:
                require(any(item["digest"] == archive["digest"] and
                            item["size"] == archive["size"]
                            for item in selected["archives"]),
                        "source archive bytes differ from source selection")
            for association_id in data["associations"]:
                association = get(association_id)
                if association:
                    require(association["archive"] == data["archive"],
                            "source association points at another archive")
                    require(association["producer"] == data["producer"],
                            "source association producer differs")
        elif kind == "build-inputs":
            check_bindings(data["dependencies"])
            for source in data["sources"]:
                selected = get(source)
                if selected:
                    require(selected["package"] == data["package"], "source package mismatch")
        elif kind == "attempt-start":
            require(data["attempt_id"] not in attempts, "attempt identity has conflicting bindings")
            attempts[data["attempt_id"]] = identity
            previous_result = get(data["retry_of"])
            prior = get(previous_result["attempt"]) if previous_result else None
            if prior:
                require(prior["attempt_id"] != data["attempt_id"], "retry must use a new attempt identity")
        elif kind == "attempt-result":
            require(data["attempt"] not in results, "multiple final results for one attempt")
            results[data["attempt"]] = identity
            start = get(data["attempt"])
            if start:
                require(timestamp(data["finished_at"]) >= timestamp(start["prepared_at"]), "result predates preparation")
            for output in data["outputs"]:
                produced = get(output)
                if produced:
                    require(produced["attempt"] == data["attempt"], "result output belongs to another attempt")
        elif kind == "package-output":
            start = get(data["attempt"])
            inputs = get(start["inputs"]) if start else None
            if inputs:
                require(inputs["package"] == data["package"], "output package mismatch")
        elif kind == "generation":
            require(data["generation_id"] not in generations, "generation identity has conflicting manifests")
            generations[data["generation_id"]] = identity
            assembly = get(data["assembly_result"])
            assembly_start = get(assembly["attempt"]) if assembly else None
            inputs = get(assembly_start["inputs"]) if assembly_start else None
            if assembly:
                require(assembly["outcome"] == "succeeded", "generation assembly did not succeed")
                output_artifacts = [a for output in assembly["outputs"] if get(output)
                                    for a in get(output)["artifacts"]]
                # Do not mistake an incomplete graph for an inconsistent one.
                if all(get(output) for output in assembly["outputs"]):
                    for key in ("artifact", "content_manifest"):
                        require(data[key] in output_artifacts, "generation artifact not produced by assembly")
            if inputs:
                require(inputs["purpose"] == "assembly", "generation needs assembly inputs")
                require({(x["output"], x["result"]) for x in inputs["dependencies"]} ==
                        {(x["output"], x["result"]) for x in data["packages"]},
                        "assembly dependencies differ from generation packages")
            check_bindings(data["packages"])

    gaps = [{"record": identity, "reasons": records[identity]["gaps"]}
            for identity in sorted(visited) if records[identity]["gaps"]]
    gap_by_kind = {}
    for item in gaps:
        kind = records[item["record"]]["kind"]
        summary = gap_by_kind.setdefault(kind, {"records": 0, "reasons": 0})
        summary["records"] += 1
        summary["reasons"] += len(item["reasons"])
    declared_gap_count = sum(len(item["reasons"]) for item in gaps)
    declared_gap_summary = {
        "record_count": len(gaps),
        "reason_count": declared_gap_count,
        "by_kind": [{"kind": kind, **gap_by_kind[kind]} for kind in sorted(gap_by_kind)],
    }
    assets = {}
    for identity in sorted(visited):
        for asset in artifact_references(records[identity]):
            previous = assets.get(asset["digest"])
            if previous and previous["size"] is not None and asset["size"] is not None:
                require(previous["size"] == asset["size"], "conflicting sizes for artifact digest")
            if previous is None or asset["size"] is not None:
                assets[asset["digest"]] = asset
    subjects = []
    for identity in bundle["roots"]:
        if identity not in visited:
            subjects.append({"record": identity, "status": "missing"})
            continue
        root = records[identity]
        data = root["data"]
        subject = {"record": identity, "kind": root["kind"], "gaps": root["gaps"]}
        if root["kind"] == "generation":
            subject["generation_id"] = data["generation_id"]
            subject["assembly_result"] = data["assembly_result"]
            packages = []
            for binding in data["packages"]:
                output = get(binding["output"])
                start = get(output["attempt"]) if output else None
                packages.append({**binding, "package": output["package"] if output else None,
                                 "inputs": start["inputs"] if start else None})
            subject["packages"] = packages
        elif root["kind"] == "verification-execution":
            for key in ("producer_observation", "check_id", "definition_digest", "subject",
                        "attempt_id", "sequence", "outcome", "granularity", "timing"):
                subject[key] = data[key]
        else:
            for key in ("package", "step", "attempt_id", "inputs", "attempt", "outcome", "summary"):
                if key in data:
                    subject[key] = data[key]
        subjects.append(subject)
    evidence = [{"result": identity, "outcome": records[identity]["data"]["outcome"],
                 "summary": records[identity]["data"]["summary"],
                 "jobs": records[identity]["data"]["jobs"],
                 "traces": records[identity]["data"]["traces"], "availability": "not-checked"}
                for identity in sorted(visited) if records[identity]["kind"] == "attempt-result"]
    snapshots = [{
        "record": identity,
        "generation": records[identity]["data"]["generation"],
        "generation_id": records[identity]["data"]["generation_id"],
        "root_inventory_digest": records[identity]["data"]["root_inventory_digest"],
        "record_set_digest": records[identity]["data"]["record_set_digest"],
        "observations": records[identity]["data"]["observations"],
    } for identity in sorted(visited)
       if records[identity]["kind"] == "generation-observation-snapshot"]
    checks = [{
        "record": identity,
        "producer": records[identity]["data"]["producer"],
        "check_id": records[identity]["data"]["check_id"],
        "definition_digest": records[identity]["data"]["definition_digest"],
        "granularity": records[identity]["data"]["granularity"],
    } for identity in sorted(visited)
       if records[identity]["kind"] == "verification-check"]
    coverage = [{
        "record": identity,
        "subject": records[identity]["data"]["subject"],
        "family": records[identity]["data"]["family"],
        "collector": records[identity]["data"]["collector"],
        "scope": records[identity]["data"]["scope"],
        "outcome": records[identity]["data"]["outcome"],
        "observation_count": records[identity]["data"]["observation_count"],
        "details": records[identity]["data"]["details"],
    } for identity in sorted(visited)
       if records[identity]["kind"] == "observation-coverage"]
    relationships = [{
        "record": identity,
        "producer_observation": records[identity]["data"]["producer_observation"],
        "subject": records[identity]["data"]["subject"],
        "relation": records[identity]["data"]["relation"],
        "target": records[identity]["data"]["target"],
        "evidence": records[identity]["data"]["evidence"],
    } for identity in sorted(visited)
       if records[identity]["kind"] == "relationship-observation"]
    source_provenance = []
    for identity in sorted(visited):
        if records[identity]["kind"] != "source-provenance":
            continue
        data = records[identity]["data"]
        associations = []
        for association_id in data["associations"]:
            association = get(association_id)
            reference = get(association["reference"]) if association else None
            repository = get(reference["repository"]) if reference else None
            associations.append({
                "record": association_id,
                "relationship": association["relationship"] if association else None,
                "reference_record": association["reference"] if association else None,
                "reference_kind": reference["kind"] if reference else None,
                "reference_value": reference["value"] if reference else None,
                "repository_record": reference["repository"] if reference else None,
                "repository": repository["location"] if repository else None,
            })
        source_provenance.append({
            "record": identity,
            "producer_observation": data["producer_observation"],
            "package": data["package"],
            "project": data["project"],
            "output": data["output"],
            "build_inputs": data["build_inputs"],
            "source_selection": data["source_selection"],
            "archive": data["archive"],
            "associations": associations,
        })
    verification = [{"record": identity,
                     "producer_observation": records[identity]["data"]["producer_observation"],
                     "check_id": records[identity]["data"]["check_id"],
                     "definition_digest": records[identity]["data"]["definition_digest"],
                     "subject": records[identity]["data"]["subject"],
                     "attempt_id": records[identity]["data"]["attempt_id"],
                     "sequence": records[identity]["data"]["sequence"],
                     "outcome": records[identity]["data"]["outcome"],
                     "execution": records[identity]["data"]["execution"],
                     "evidence": records[identity]["data"]["evidence"],
                     "timing": records[identity]["data"]["timing"]}
                    for identity in sorted(visited)
                    if records[identity]["kind"] == "verification-execution"]
    reference_closure_complete = not missing
    declared_gap_free = not gaps
    return {"schema_version": 1, "roots": bundle["roots"], "records": sorted(visited),
            "missing_records": sorted(missing), "missing_record_count": len(missing),
            "reference_closure_complete": reference_closure_complete,
            "gaps": gaps, "declared_gap_free": declared_gap_free,
            "declared_gap_count": declared_gap_count,
            "declared_gap_record_count": len(gaps),
            "declared_gap_summary": declared_gap_summary,
            "subjects": subjects, "evidence": evidence,
            "snapshots": snapshots, "verification": verification,
            "verification_checks": checks,
            "coverage": coverage, "relationships": relationships,
            "source_provenance": source_provenance,
            "complete": reference_closure_complete and declared_gap_free,
            "artifacts": [assets[x] for x in sorted(assets)],
            "artifact_verification": "not-checked", "authenticity": "not-verified"}


def verify_artifacts(bundle: dict, paths: dict[str, str | Path]) -> dict:
    """Read only explicit caller-authorized paths; never follow record locators."""
    report = inspect(bundle)
    checked = []
    for asset in report["artifacts"]:
        path = paths.get(asset["digest"])
        status = "not-provided"
        if path is not None:
            try:
                h, size = hashlib.sha256(), 0
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    require(stat.S_ISREG(before.st_mode), "artifact path must be a regular file")
                    while chunk := stream.read(1024 * 1024):
                        h.update(chunk)
                        size += len(chunk)
                    after = os.fstat(stream.fileno())
                    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                            (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                            "artifact changed during verification")
                status = "verified" if ("sha256:" + h.hexdigest() == asset["digest"] and
                                       (asset["size"] is None or size == asset["size"])) else "mismatch"
            except OSError:
                status = "unavailable"
        checked.append({"digest": asset["digest"], "status": status})
    report["artifact_verification"] = checked
    return report


def compare(before: dict, after: dict) -> dict:
    """Compare declared package inputs in two single-generation bundles."""
    def packages(bundle):
        report = inspect(bundle)
        require(not report["missing_records"], "comparison requires all referenced records")
        require(len(bundle["roots"]) == 1, "comparison requires one generation root")
        records = bundle["records"]
        root = records[bundle["roots"][0]]
        require(root["kind"] == "generation", "comparison root must be a generation")
        result = {}
        for item in root["data"]["packages"]:
            output = records[item["output"]]["data"]
            start = records[output["attempt"]]["data"] if output["attempt"] else None
            result[output["package"]] = {
                "output": item["output"], "inputs": start["inputs"] if start else None}
        assembly_result = records[root["data"]["assembly_result"]]["data"]
        assembly = records[assembly_result["attempt"]]["data"]["inputs"]
        return result, assembly, report["gaps"]

    old, old_assembly, old_gaps = packages(before)
    new, new_assembly, new_gaps = packages(after)
    changes = []
    for name in sorted(old.keys() | new.keys()):
        left, right = old.get(name), new.get(name)
        if left != right:
            changed_fields = []
            if left and right and left["inputs"] and right["inputs"]:
                a = before["records"][left["inputs"]]["data"]
                b = after["records"][right["inputs"]]["data"]
                changed_fields = [key for key in sorted(a) if a[key] != b[key]]
            changes.append({"package": name, "before": left, "after": right,
                            "changed_input_fields": changed_fields})
    return {"schema_version": 1, "packages": changes,
            "assembly_inputs_changed": old_assembly != new_assembly,
            "before_gaps": old_gaps, "after_gaps": new_gaps}
