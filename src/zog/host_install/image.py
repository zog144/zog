"""Assemble new regular files only, with durable operation evidence.

An existing destination is never opened for writing. Interrupted jobs retain their
operation directory and are inspected, never automatically resumed or overwritten.
"""
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import uuid
from pathlib import Path

from . import InstallError
from .layout import SECTOR, plan, regions, verify
from .manifest import MIB, canonical, digest, require, validate


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def record(path, value):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("xb") as out:
        out.write(canonical(value) + b"\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    sync_dir(path.parent)


def open_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "artifact must be a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def hash_region(file, offset, size):
    h = hashlib.sha256()
    file.seek(offset)
    remaining = size
    while remaining:
        chunk = file.read(min(MIB, remaining))
        require(bool(chunk), "unexpected end of image")
        h.update(chunk)
        remaining -= len(chunk)
    return h.hexdigest()


def check_filesystem(file, kind, size, expected_uuid=None):
    """Check geometry/identity, not filesystem consistency or bootability."""
    file.seek(0)
    if kind == "ext4":
        file.seek(1024)
        sb = file.read(1024)
        require(len(sb) == 1024 and sb[56:58] == b"\x53\xef", "missing ext filesystem superblock")
        block_log = struct.unpack_from("<I", sb, 24)[0]
        require(block_log <= 6, "unsupported ext block size")
        incompat = struct.unpack_from("<I", sb, 96)[0]
        require(incompat & 0x40, "ext4 extents feature missing")
        blocks = struct.unpack_from("<I", sb, 4)[0]
        if incompat & 0x80:
            blocks += struct.unpack_from("<I", sb, 336)[0] << 32
        require(blocks * (1024 << block_log) == size, "ext filesystem size differs from partition")
        require(str(uuid.UUID(bytes=sb[104:120])) == expected_uuid, "ext filesystem UUID mismatch")
    else:
        boot = file.read(512)
        require(len(boot) == 512 and boot[510:512] == b"\x55\xaa", "missing FAT boot signature")
        bps = struct.unpack_from("<H", boot, 11)[0]
        spc = boot[13]
        reserved = struct.unpack_from("<H", boot, 14)[0]
        fats = boot[16]
        sectors = struct.unpack_from("<I", boot, 32)[0]
        fat_size = struct.unpack_from("<I", boot, 36)[0]
        require(bps == 512 and spc in (1, 2, 4, 8, 16, 32, 64, 128) and reserved >= 1 and
                fats in (1, 2) and fat_size > 0 and sectors * bps == size and
                struct.unpack_from("<H", boot, 17)[0] == 0 and
                struct.unpack_from("<H", boot, 22)[0] == 0, "invalid FAT32 geometry")
        clusters = (sectors - reserved - fats * fat_size) // spc
        require(65525 <= clusters < 0x0FFFFFF5 and fat_size * bps >= (clusters + 2) * 4,
                "invalid FAT32 cluster count/table capacity")


def snapshot_artifact(base, a, destination, expected_uuid=None):
    base = Path(base).resolve(strict=True)
    path = base / a["path"]
    # Reject intermediate symlinks too; artifact input directories must be trusted/quiescent.
    cursor = base
    for component in Path(a["path"]).parts:
        cursor = cursor / component
        require(not cursor.is_symlink(), "symlink artifact path rejected")
    with open_regular(path) as source, destination.open("xb") as target:
        before = os.fstat(source.fileno())
        require(before.st_size == a["bytes"], "artifact size mismatch")
        h = hashlib.sha256()
        left = a["bytes"]
        while left:
            chunk = source.read(min(MIB, left))
            require(bool(chunk), "truncated artifact")
            target.write(chunk)
            h.update(chunk)
            left -= len(chunk)
        require(not source.read(1), "artifact grew during snapshot")
        after = os.fstat(source.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "artifact changed during snapshot")
        require(h.hexdigest() == a["sha256"], "artifact SHA-256 mismatch")
        target.flush()
        os.fsync(target.fileno())
    with destination.open("rb") as source:
        check_filesystem(source, a["format"], a["bytes"], expected_uuid)


def install(manifest, artifact_directory, operation_directory, disk_bytes):
    """Create operation_directory/disk.img exclusively. Never write a block device."""
    m = json.loads(canonical(validate(manifest)))
    p = plan(m, disk_bytes)
    mkfs = shutil.which("mkfs.ext4")
    require(mkfs is not None, "mkfs.ext4 is required before creating an operation")
    op = Path(operation_directory).absolute()
    require(op.parent.is_dir(), "operation parent directory must exist")
    op.mkdir(mode=0o700)  # exclusive: existing files, symlinks and directories fail here
    sync_dir(op.parent)
    state = {"schema": 1, "operation_id": str(uuid.uuid4()), "status": "prepared",
             "manifest": m, "manifest_sha256": digest(m), "layout": p,
             "partition_sha256": {}, "bootability": "not-tested", "self_contained_zog_boot": False}
    record(op / "operation.json", state)
    try:
        for name, index in (("esp", 0), ("rootfs", 1)):
            snapshot_artifact(artifact_directory, m["artifacts"][name], op / f"{name}.img",
                              p["partitions"][index]["filesystem_uuid"])
        for part in p["partitions"][2:]:
            fs = op / f"{part['role']}.img"
            with fs.open("xb") as out:
                out.truncate(part["mib"] * MIB)
            result = subprocess.run([mkfs, "-q", "-F", "-t", "ext4", "-U", part["filesystem_uuid"],
                "-L", part["role"], "-E", "lazy_itable_init=0,lazy_journal_init=0", str(fs)],
                capture_output=True, text=True)
            require(result.returncode == 0, f"filesystem creation failed for {part['role']}: {result.stderr[-2000:]}")
            with fs.open("rb") as inp:
                check_filesystem(inp, "ext4", part["mib"] * MIB, part["filesystem_uuid"])
                os.fsync(inp.fileno())
        sync_dir(op)
        state["status"] = "inputs-ready"
        record(op / "operation.json", state)
        with (op / "disk.img").open("x+b") as disk:
            st = os.fstat(disk.fileno())
            require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "unsafe output file")
            state["target"] = {"device": st.st_dev, "inode": st.st_ino, "bytes": disk_bytes}
            state["status"] = "writing"
            record(op / "operation.json", state)
            disk.truncate(disk_bytes)
            for offset, data in regions(p):
                disk.seek(offset)
                disk.write(data)
            for part, filename in zip(p["partitions"],
                                     ("esp.img", "rootfs.img", "HOST-B.img", "STATE.img", "APPLICATIONS.img")):
                disk.seek(part["first_lba"] * SECTOR)
                h = hashlib.sha256()
                with (op / filename).open("rb") as source:
                    while chunk := source.read(MIB):
                        disk.write(chunk)
                        h.update(chunk)
                state["partition_sha256"][part["role"]] = h.hexdigest()
            disk.flush()
            os.fsync(disk.fileno())
        state["status"] = "validating"
        record(op / "operation.json", state)
        report = inspect(op, state)
        record(op / "validation.json", report)
        state["status"] = "complete"
        record(op / "operation.json", state)
        return {"operation": str(op), "status": "complete", "disk_image": str(op / "disk.img"),
                "validation": report}
    except BaseException as exc:
        # If the error record cannot be persisted, preserve the last durable state.
        state["status"] = "incomplete"
        state["error"] = f"{type(exc).__name__}: {exc}"
        try:
            record(op / "operation.json", state)
        except OSError:
            pass
        raise


def inspect(operation_directory, state=None):
    op = Path(operation_directory)
    if state is None:
        with open_regular(op / "operation.json") as source:
            state = json.load(source)
    require(state.get("schema") == 1, "unsupported operation schema")
    m = validate(state["manifest"])
    require(digest(m) == state["manifest_sha256"], "operation manifest changed")
    expected = plan(m, state["layout"]["disk_bytes"])
    require(expected == state["layout"], "operation layout changed")
    require(state["status"] in ("validating", "complete"),
            f"operation is {state['status']}; interrupted installation must not be promoted")
    with open_regular(op / "disk.img") as disk:
        st = os.fstat(disk.fileno())
        require(state["target"] == {"device": st.st_dev, "inode": st.st_ino, "bytes": st.st_size}
                and st.st_nlink == 1, "prepared output identity changed")
        report = verify(disk, expected)
        for part in expected["partitions"]:
            require(hash_region(disk, part["first_lba"] * SECTOR, part["mib"] * MIB) ==
                    state["partition_sha256"].get(part["role"]),
                    f"partition content changed: {part['role']}")
    report.update(integrity="matched", bootability="not-tested", self_contained_zog_boot=False,
                  boot_provider=m["boot"], operation_status=state["status"])
    return report
