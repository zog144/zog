"""Controlled fixture, not a real package build. Run with an unused destination."""
import hashlib
import json
import sys
from pathlib import Path
from zog.build_record import Store, canonical, make_record, record_id, verify_artifacts


def fixture(*, source_bytes=b"fixture source", recipe_bytes=b"fixture recipe", legacy=False):
    records, blobs, ids = {}, {}, {}
    def asset(name, raw):
        identity = "sha256:" + hashlib.sha256(raw).hexdigest()
        blobs[identity] = raw
        return {"name": name, "digest": identity, "size": len(raw)}
    def add(label, kind, data, gaps=None):
        record = make_record(kind, data, gaps=gaps)
        identity = record_id(record)
        records[identity] = record
        ids[label] = identity
        return identity
    source = asset("source.tar", source_bytes)
    pin = asset("commit-pin.py", b"fixture literal monthly pin")
    selected = add("source", "source-selection", {
        "package": "demo-package", "pin": {"month": "2026-10-01",
        "repository": "fixture:catalogue", "revision": "1" * 40,
        "path": "pins/2026-10-01/commit-pin.py", "digest": pin["digest"]},
        "upstream": [{"repository": "fixture:upstream", "revision": "2" * 40}], "archives": [source]})
    inputs = add("inputs", "build-inputs", {
        "package": "demo-package", "step": "final", "purpose": "package", "sources": [selected],
        "recipe": asset("recipe-manifest.json", recipe_bytes), "patches": [],
        "target": "x86_64-linux", "options": {"tests": "enabled"},
        "environment": {"LC_ALL": "C", "SOURCE_DATE_EPOCH": "1790899200"},
        "materials": [asset("bootstrap-manifest.json", b"fixture compiler and build root identity")],
        "dependencies": []})
    start = add("failed_start", "attempt-start", {"attempt_id": "fixture:package:1", "inputs": inputs,
        "prepared_at": "2026-10-02T12:00:00Z", "retry_of": None})
    failed = add("failed_result", "attempt-result", {"attempt": start, "outcome": "failed",
        "finished_at": "2026-10-02T12:01:00Z", "jobs": [{"host_id": "fixture-host", "job_id": "job-1"}],
        "traces": [{"host_id": "fixture-host", "build_id": "attempt:fixture-1"}],
        "outputs": [], "summary": "Controlled failure fixture"})
    retry = add("start", "attempt-start", {"attempt_id": "fixture:package:2", "inputs": inputs,
        "prepared_at": "2026-10-02T12:02:00Z", "retry_of": failed})
    output = add("output", "package-output", {"package": "demo-package", "attempt": None if legacy else retry,
        "artifacts": [asset("package-output.tar", b"fixture package output")]},
        gaps=["Legacy output has no captured producing attempt"] if legacy else None)
    result = None
    if not legacy:
        result = add("result", "attempt-result", {"attempt": retry, "outcome": "succeeded",
            "finished_at": "2026-10-02T12:03:00Z", "jobs": [{"host_id": "fixture-host", "job_id": "job-2"}],
            "traces": [{"host_id": "fixture-host", "build_id": "attempt:fixture-2"}],
            "outputs": [output], "summary": "Controlled successful retry fixture"})
    assembly_inputs = add("assembly_inputs", "build-inputs", {
        "package": "rootfs", "step": "assemble", "purpose": "assembly", "sources": [],
        "recipe": asset("assembly-manifest.json", b"fixture assembly actions including configuration"),
        "patches": [], "target": "x86_64-linux", "options": {}, "environment": {"LC_ALL": "C"},
        "materials": [asset("assembly-tool.json", b"fixture assembler identity")], "dependencies": [{"output": output, "result": result}]})
    assembly_start = add("assembly_start", "attempt-start", {"attempt_id": "fixture:assembly:1",
        "inputs": assembly_inputs, "prepared_at": "2026-10-02T12:04:00Z", "retry_of": None})
    rootfs = asset("rootfs.tar", b"fixture assembled rootfs (not bootable)")
    content = asset("content-manifest.json", b"fixture file inventory")
    assembly_output = add("assembly_output", "package-output", {"package": "rootfs",
        "attempt": assembly_start, "artifacts": [rootfs, content]})
    assembly_result = add("assembly_result", "attempt-result", {"attempt": assembly_start,
        "outcome": "succeeded", "finished_at": "2026-10-02T12:05:00Z",
        "jobs": [{"host_id": "fixture-host", "job_id": "assembly-job"}],
        "traces": [{"host_id": "fixture-host", "build_id": "attempt:fixture-assembly"}],
        "outputs": [assembly_output], "summary": "Controlled assembly fixture"})
    root = add("generation", "generation", {"generation_id": "fixture:generation:1",
        "assembly_result": assembly_result, "packages": [{"output": output, "result": result}],
        "artifact": rootfs, "content_manifest": content,
        "verification": [asset("checks.json", b"fixture verification report")]})
    return {"schema_version": 1, "roots": [root], "records": records}, blobs, ids


def main(destination):
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=False)
    bundle, blobs, ids = fixture()
    store = Store(directory / "records")
    for record in bundle["records"].values():
        store.put(record)
    recovered = Store(directory / "records")
    assert record_id(recovered.get(ids["start"])) == ids["start"]
    bundle = recovered.bundle(bundle["roots"])
    paths = {}
    (directory / "artifacts").mkdir()
    for identity, raw in blobs.items():
        path = directory / "artifacts" / identity[7:]
        path.write_bytes(raw)
        paths[identity] = str(path.resolve())
    (directory / "bundle.json").write_bytes(canonical(bundle))
    (directory / "artifact-paths.json").write_bytes(canonical(paths))
    print(json.dumps(verify_artifacts(bundle, paths), indent=2))

if __name__ == "__main__":
    main(sys.argv[1])
