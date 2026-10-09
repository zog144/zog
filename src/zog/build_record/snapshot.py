"""Canonical immutable generation observation snapshots."""
from __future__ import annotations

from .model import make_record, snapshot_record_set_digest


def generation_observation_snapshot(
        generation: str, generation_id: str, root_inventory_digest: str, *,
        verification_checks=(), verification_executions=(), relationships=(),
        source_provenance=(), coverage=()):
    """Create one immutable snapshot; persistence/publication remain owner actions."""
    observations = {
        "verification_checks": sorted(verification_checks),
        "verification_executions": sorted(verification_executions),
        "relationships": sorted(relationships),
        "source_provenance": sorted(source_provenance),
        "coverage": sorted(coverage),
    }
    return make_record("generation-observation-snapshot", {
        "generation": generation,
        "generation_id": generation_id,
        "root_inventory_digest": root_inventory_digest,
        "observations": observations,
        "record_set_digest": snapshot_record_set_digest(generation, observations),
    })
