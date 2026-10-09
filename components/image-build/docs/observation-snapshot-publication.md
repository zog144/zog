# Canonical observation snapshot publication

Image-build owns publication and selection of canonical build-record observation
snapshots. Build-record owns immutable record identity/storage and build-trace reads
caller-selected snapshot IDs; neither downstream program scans the record store to
infer a preferred or newest snapshot.

For a provenance-enabled generation the owner flow is:

```text
verify immutable generation
-> derive image-build integration observations
-> freeze pending owner publication intent
-> canonicalize through build-record 0.7.2+
-> Store.put prerequisite records in adapter order
-> Store.put generation-observation-snapshot last
-> verify the complete canonical closure
-> retain an immutable owner publication receipt
-> atomically select that exact snapshot ID
-> clear the pending intent
```

The pending intent contains the complete producer envelope and the exact canonical
record IDs. If storage or pointer publication returns an uncertain result, recovery
reuses that envelope even if newer verification observations have appeared meanwhile.
After recovery completes, a later explicit refresh can publish a second immutable
snapshot for the same generation.

Owner state lives under:

```text
state/image-build/build-record/observation-snapshots/<generation>/
    pending.json
    selected.json
    publications/<snapshot-hex>.json
```

A record existing under `build-record/records/` is not publication. A publication
receipt is not automatically selection. `selected.json` is the explicit owner
choice and never means "newest by timestamp".

Normal provenance-enabled generation publication creates an initial selected snapshot
when none exists. Reusing that generation verifies/reuses the existing selection; it
does not silently incorporate later observations. Use the explicit owner operation to
refresh:

```python
receipt = builder.publish_observation_snapshot(selection)
snapshot_id = receipt["snapshot"]

current = builder.selected_observation_snapshot(selection.generation)
published = builder.observation_snapshots(selection.generation)
```

For retained generations, no rebuild is required. With the original provenance
configuration:

```sh
python -m zog.image_build.observation_snapshots \
  --state PROJECT/state \
  --provenance-config provenance.json \
  publish PROJECT/state/image-build/generations/GENERATION

python -m zog.image_build.observation_snapshots \
  --state PROJECT/state \
  --provenance-config provenance.json \
  selected GENERATION
```

The returned `sha256:...` snapshot is the exact ID to supply to build-trace and
integrate-observe. Listing reads only image-build's owner publication namespace and
verifies every returned receipt against canonical build-record storage; it never
performs store-wide snapshot discovery or chronology inference.


## Production discovery contract

The supported owner APIs return immutable receipt data with the stable fields:

```text
schema
host_id
project_id
generation
generation_record
snapshot
root_inventory_digest
record_set_digest
```

`observation_snapshots()` adds only the boolean `selected` marker to each published
receipt. Selection remains explicit owner state; neither API scans canonical
build-record storage or infers chronology.

The remote execution contract exposes the same owner selection through
`generation.inspect`:

```text
provenance.observation_snapshot   # complete owner receipt
provenance.build_trace.snapshot   # exact sha256 snapshot ID
```

A provenance-enabled generation with no owner-selected snapshot reports
`missing_evidence: [{"kind": "observation-snapshot", ...}]`. It does not manufacture
or infer a selection. Completed pipeline records retain the same exact snapshot ID in
`observation_snapshot`.

Explicit remote refresh/list operations are deliberately deferred. Normal production
requires automatic initial publication and `generation.inspect` discovery, while
retained-generation acceptance can use the maintained
`zog.image_build.observation_snapshots` CLI for explicit publish/list/selected
operations. Adding a second remote mutation surface is not required for the next live
acceptance.

## Retained-generation backfill

Publishing observation metadata for a retained generation does not rebuild packages
or create another generation. It requires the retained immutable generation, the
original compatible provenance configuration/canonical build-record store, and the
inspection tools used by the producer (including `readelf` for ELF observations).
The generation manifest and root inventory remain unchanged; only owner snapshot state
and canonical observation records are added.
