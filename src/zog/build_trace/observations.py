"""Read-only integrate-observe projections over versioned producer observations."""
import json
from pathlib import Path

from .api import BuildTrace as _BaseBuildTrace, checked
from .generations import Reader, hex_id
from .model import TraceError, limit_value, paginate, response
from .provenance import library
from .snapshot_observations import SnapshotObservationMixin
from .history import HistoryMixin

GENERATION_SCHEMA = "image-build-integration-observations-v1"
CANDIDATE_SCHEMA = "image-build-candidate-verifications-v1"
COLLECTIONS = ("checks", "verification", "relationships", "sources", "gaps")
RELATIONS = frozenset({
    "needs-library", "provides-soname", "elf-interpreter", "script-interpreter",
    "declares-build-dependency", "declares-test-dependency",
    "declares-runtime-dependency", "used-build-output",
})
MAX_OBSERVATION_BYTES = 32 * 1024 * 1024


def _observation_library():
    lib = library()
    required = (
        "loads", "record_id", "verification_execution", "relationship_observation",
        "source_provenance_records", "validate_image_build_candidate",
        "validate_image_build_generation",
    )
    if any(not callable(getattr(lib, name, None)) for name in required):
        raise TraceError(
            "dependency-unavailable",
            "Install build-record 0.5.0 or newer for observation inspection.",
        )
    return lib


class ObservationFileProvider:
    """Expose one explicit image-build producer export without inventing a store."""

    def __init__(self, path):
        source = Path(path)
        if source.is_symlink():
            raise TraceError("source-unavailable", "Observation input must not be a symlink.")
        try:
            raw = source.read_bytes()
        except OSError:
            raise TraceError("source-unavailable", "Observation input cannot be read.") from None
        if len(raw) > MAX_OBSERVATION_BYTES:
            raise TraceError("source-too-large", "Observation input exceeds 32 MiB.")
        try:
            self.value = _observation_library().loads(raw, limit=MAX_OBSERVATION_BYTES)
        except ValueError:
            raise TraceError("invalid-record", "Observation input is malformed.") from None
        self.source = str(source)

    def generation(self, generation):
        return self.value

    def candidate(self, candidate):
        return self.value


def _attempt_scope(trace, observation):
    try:
        owner = json.loads(observation["attempt_id"])
    except (ValueError, TypeError):
        raise TraceError("invalid-record", "Verification attempt identity is malformed.") from None
    if (not isinstance(owner, list) or len(owner) != 3 or
            owner[:2] != [trace.host_id, trace.record_project_id] or
            not isinstance(owner[2], str) or not owner[2]):
        raise TraceError("not-found", "Verification observation is outside the authorized scope.")
    build_id = "attempt:" + owner[2]
    if not trace._permitted(build_id):
        raise TraceError("not-found", "Verification observation is outside the authorized scope.")
    for evidence in observation.get("evidence", []):
        if evidence.get("kind") == "build-trace":
            if (evidence.get("host_id") != trace.host_id or
                    not isinstance(evidence.get("build_id"), str) or
                    not trace._permitted(evidence["build_id"])):
                raise TraceError("not-found", "Verification evidence is outside the authorized scope.")
    return build_id


def _verification_item(trace, lib, observation):
    build_id = _attempt_scope(trace, observation)
    record = lib.verification_execution(observation)
    identity = lib.record_id(record)
    data = record["data"]
    return dict(
        id=identity,
        record=identity,
        producer_observation=data["producer_observation"],
        check_id=data["check_id"],
        definition_digest=data["definition_digest"],
        subject=data["subject"],
        attempt_id=data["attempt_id"],
        build_id=build_id,
        sequence=data["sequence"],
        outcome=data["outcome"],
        execution=data["execution"],
        environment_digest=data["environment_digest"],
        evidence=data["evidence"],
        granularity=data["granularity"],
        timing=data["timing"],
        authority="build-record",
        canonical_kind="verification-execution",
        persistence="not-checked",
    )


def _relationship_item(lib, observation):
    record = lib.relationship_observation(observation)
    identity = lib.record_id(record)
    return dict(
        id=identity,
        record=identity,
        producer_observation=record["data"]["producer_observation"],
        subject=record["data"]["subject"],
        relation=record["data"]["relation"],
        target=record["data"]["target"],
        evidence=record["data"]["evidence"],
        gaps=record["gaps"],
        authority="build-record",
        canonical_kind="relationship-observation",
        persistence="not-checked",
    )


def _source_item(lib, observation):
    records = lib.source_provenance_records(observation)
    projected = []
    provenance = None
    for record in records:
        identity = lib.record_id(record)
        projected.append(dict(record=identity, kind=record["kind"],
                              data=record["data"], gaps=record["gaps"]))
        if record["kind"] == "source-provenance":
            provenance = (identity, record)
    if provenance is None:
        raise TraceError("invalid-record", "Canonical source provenance root is unavailable.")
    identity, root = provenance
    data = root["data"]
    return dict(
        id=identity,
        record=identity,
        producer_observation=data["producer_observation"],
        package=data["package"],
        project=data["project"],
        output=data["output"],
        build_inputs=data["build_inputs"],
        source_selection=data["source_selection"],
        archive=data["archive"],
        associations=data["associations"],
        canonical_records=projected,
        gaps=root["gaps"],
        authority="build-record",
        canonical_kind="source-provenance",
        persistence="not-checked",
    )


def _producer_item(value):
    return dict(value, authority="image-build-producer", canonical_record=None,
                canonicalization="not-yet-defined")


def _relationship_package(row, package):
    subject = row["subject"]
    if subject["kind"] == "package":
        return subject["package"] == package
    return package in subject.get("packages", [])


class BuildTrace(HistoryMixin, SnapshotObservationMixin, _BaseBuildTrace):
    """Public build-trace facade with additive observation-query methods."""

    def __init__(self, *args, observation_provider=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.observation_provider = observation_provider

    def _provider(self):
        if self.observation_provider is None:
            return None
        for name in ("generation", "candidate"):
            if not callable(getattr(self.observation_provider, name, None)):
                raise TraceError(
                    "invalid-query",
                    "Observation provider does not implement the required read-only interface.",
                )
        return self.observation_provider

    def _generation_observation(self, generation):
        hex_id(generation)
        provider = self._provider()
        if provider is None:
            return None, None
        if self.record_project_id is None:
            raise TraceError("invalid-query", "Generation observations require a canonical project identity.")
        reader = Reader(self)
        pointer, bundle, report, _ = reader.generation(generation)
        if pointer is None:
            metrics = reader.finish()
            return None, metrics
        try:
            value = provider.generation(generation)
            lib = reader.lib
            required = (
                "record_id", "verification_execution", "relationship_observation",
                "source_provenance_records", "validate_image_build_generation",
            )
            if any(not callable(getattr(lib, name, None)) for name in required):
                raise TraceError(
                    "dependency-unavailable",
                    "Install build-record 0.5.0 or newer for observation inspection.",
                )
            lib.validate_image_build_generation(value, bundle)
            for item in value["verification"]["results"]:
                _attempt_scope(self, item)
            metrics = reader.finish()
            return value, metrics
        except Exception:
            try:
                reader.finish()
            except Exception:
                pass
            raise

    def _candidate_observation(self, candidate):
        hex_id(candidate)
        provider = self._provider()
        if provider is None:
            return None
        if self.record_project_id is None:
            raise TraceError("invalid-query", "Candidate observations require a canonical project identity.")
        value = provider.candidate(candidate)
        lib = _observation_library()
        lib.validate_image_build_candidate(value)
        expected = json.dumps([self.host_id, self.record_project_id, candidate], separators=(",", ":"))
        if value["generation_id"] != expected:
            raise TraceError("not-found", "Candidate observation is outside the authorized scope.")
        for item in value["results"]:
            _attempt_scope(self, item)
        return value

    @checked
    def generation_observations(self, generation, *, collection=None, relation=None,
                                package=None, cursor=None, limit=20):
        if collection is not None and collection not in COLLECTIONS:
            raise TraceError("invalid-query", "Unsupported generation observation collection.")
        if collection is None and (cursor is not None or relation is not None or package is not None):
            raise TraceError("invalid-query", "Collection filters and cursors require a selected collection.")
        if relation is not None:
            if collection != "relationships" or relation not in RELATIONS:
                raise TraceError("invalid-query", "relation is only valid for a known relationship collection value.")
        if package is not None:
            if collection not in ("relationships", "sources") or not isinstance(package, str) or not package.strip():
                raise TraceError("invalid-query", "package is only valid for relationship or source collections.")
        if collection is not None:
            limit_value(limit)

        value, metrics = self._generation_observation(generation)
        if value is None:
            kind = "generation-observation-collection" if collection else "generation-observations"
            base = dict(
                generation=generation,
                availability="not-configured" if self.observation_provider is None
                else "not-captured-or-unavailable",
            )
            if collection:
                base.update(collection=collection, items=dict(items=[], has_more=False, next_cursor=None))
            return response(kind, **base, inspection=metrics)

        lib = _observation_library()
        verification = [_verification_item(self, lib, item)
                        for item in value["verification"]["results"]]
        checks = [dict(id=str(index).zfill(8), position=index + 1, **item,
                       authority="image-build-producer", canonical_record=None)
                  for index, item in enumerate(value["verification"]["checks"])]
        relationships = [_relationship_item(lib, item) for item in value["relationships"]]
        sources = [_source_item(lib, item) for item in value["sources"]]
        gaps = [dict(id=str(index).zfill(8), position=index + 1, gap=item,
                     authority="image-build-producer", canonical_record=None)
                for index, item in enumerate(value["gaps"])]

        if relation is not None:
            relationships = [item for item in relationships if item["relation"] == relation]
        if package is not None:
            if collection == "relationships":
                relationships = [item for item in relationships if _relationship_package(item, package)]
            elif collection == "sources":
                sources = [item for item in sources if item["package"] == package]

        rows = dict(
            checks=checks,
            verification=verification,
            relationships=relationships,
            sources=sources,
            gaps=gaps,
        )
        authority = {
            "checks": "image-build-producer",
            "verification": "build-record",
            "relationships": "build-record",
            "sources": "build-record",
            "gaps": "image-build-producer",
        }
        canonicalization = {
            "checks": "not-yet-defined",
            "verification": "verification-execution",
            "relationships": "relationship-observation",
            "sources": "source-provenance-chain",
            "gaps": "not-yet-defined",
        }

        if collection is None:
            metadata = {
                name: dict(
                    count=len(items),
                    authority=authority[name],
                    canonicalization=canonicalization[name],
                    operation=dict(operation="generation-observations",
                                   generation=generation, collection=name),
                )
                for name, items in rows.items()
            }
            return response(
                "generation-observations",
                generation=generation,
                generation_record=value["context"]["generation_record"],
                availability="available",
                envelope=value["id"],
                producer=value["producer"],
                context=value["context"],
                collections=metadata,
                coverage=dict(
                    verification=value["verification"]["coverage"],
                    observations=value["coverage"],
                    authority="image-build-producer",
                    canonicalization="not-yet-defined",
                ),
                derivation=value["derivation"],
                interpretation=(
                    "Verification, relationship and source provenance facts have deterministic "
                    "build-record identities; checks, coverage and general gaps remain producer facts."
                ),
                inspection=metrics,
            )

        page = paginate(
            rows[collection],
            scope=[
                self.scope, str(self.record_store), self.record_project_id,
                "generation-observations", generation, value["id"], collection,
                relation, package,
            ],
            cursor=cursor,
            limit=limit,
        )
        return response(
            "generation-observation-collection",
            generation=generation,
            generation_record=value["context"]["generation_record"],
            availability="available",
            envelope=value["id"],
            collection=collection,
            filters=dict(relation=relation, package=package),
            items=page,
            authority=authority[collection],
            canonicalization=canonicalization[collection],
            persistence=("not-checked" if authority[collection] == "build-record" else None),
            coverage=(value["verification"]["coverage"] if collection in ("checks", "verification")
                      else value["coverage"]),
            inspection=metrics,
        )

    @checked
    def candidate_verifications(self, candidate, *, cursor=None, limit=20):
        limit_value(limit)
        value = self._candidate_observation(candidate)
        if value is None:
            return response(
                "candidate-verifications",
                candidate=candidate,
                availability="not-configured",
                results=dict(items=[], has_more=False, next_cursor=None),
            )
        lib = _observation_library()
        rows = [_verification_item(self, lib, item) for item in value["results"]]
        page = paginate(
            rows,
            scope=[self.scope, self.record_project_id, "candidate-verifications",
                   candidate, value["generation_id"]],
            cursor=cursor,
            limit=limit,
        )
        return response(
            "candidate-verifications",
            candidate=candidate,
            generation_id=value["generation_id"],
            availability="available",
            result_count=len(rows),
            results=page,
            coverage=value["coverage"],
            authority="build-record",
            canonicalization="verification-execution",
            persistence="not-checked",
            interpretation="Absence is not SKIP and no published generation is implied.",
        )
