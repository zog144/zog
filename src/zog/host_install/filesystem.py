"""Populate an ext4 test image from a successfully staged image-build artifact.

No boot bundle overlays or host-specific state are added. EFI preparation, mount
mapping and service composition remain explicit blockers.
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from .artifact import upstream_verify, verify_tree
from .image import check_filesystem, open_regular, record, sync_dir
from .manifest import MIB, identifier, require


def build_root_fixture(staging_directory, operation_directory, mib, filesystem_uuid):
    require(os.geteuid() == 0 and os.getegid() == 0,
            "all-root-v1 filesystem population requires uid/gid 0")
    require(type(mib) is int and mib >= 64, "root filesystem image must be at least 64 MiB")
    identifier(filesystem_uuid, "root filesystem UUID")
    mkfs, fsck = shutil.which("mkfs.ext4"), shutil.which("e2fsck")
    require(mkfs is not None and fsck is not None, "mkfs.ext4 and e2fsck are required")
    staging = Path(staging_directory).resolve(strict=True)
    with open_regular(staging / "staging.json") as inp:
        status = json.load(inp)
    require(status.get("status") == "staged-for-offline-tests", "artifact staging is incomplete")
    upstream_verify(staging / "bundle", status["artifact_id"])
    root = staging / "rootfs"
    verify_tree(staging / "bundle/rootfs.tar", root)
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for path in [Path(directory), *(Path(directory) / n for n in subdirs + files)]:
            st = path.lstat()
            require(st.st_uid == st.st_gid == 0, "all-root-v1 source ownership must be root:root")
            require(not os.listxattr(path, follow_symlinks=False), "source extended attributes unsupported")
            require(not stat.S_ISREG(st.st_mode) or st.st_nlink == 1, "source hardlinks unsupported")
    op = Path(operation_directory).absolute()
    op.mkdir(mode=0o700)
    sync_dir(op.parent)
    evidence = {"schema": 1, "status": "prepared", "artifact_id": status["artifact_id"],
                "installable": False, "filesystem_uuid": filesystem_uuid, "bytes": mib * MIB,
                "boot_bundle_installed": False, "bootability": "not-tested"}
    record(op / "filesystem.json", evidence)
    try:
        image = op / "rootfs.img"
        with image.open("xb") as out:
            out.truncate(mib * MIB)
        result = subprocess.run([mkfs, "-q", "-F", "-U", filesystem_uuid, "-L", "HOST-A",
                                 "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", str(root), str(image)],
                                capture_output=True, text=True)
        require(result.returncode == 0, f"ext4 population failed: {result.stderr[-2000:]}")
        verify_tree(staging / "bundle/rootfs.tar", root)
        checked = subprocess.run([fsck, "-f", "-n", str(image)], capture_output=True, text=True)
        require(checked.returncode == 0, f"ext4 check failed: {checked.stderr[-2000:]}")
        with open_regular(image) as inp:
            check_filesystem(inp, "ext4", mib * MIB, filesystem_uuid)
            inp.seek(0)
            evidence["sha256"] = hashlib.file_digest(inp, "sha256").hexdigest()
            os.fsync(inp.fileno())
        evidence.update(status="complete-offline-fixture", fsck="passed",
                        validation_scope="filesystem consistency; bootability not tested")
        record(op / "filesystem.json", evidence)
        return evidence
    except BaseException as exc:
        evidence.update(status="incomplete", error=f"{type(exc).__name__}: {exc}")
        try:
            record(op / "filesystem.json", evidence)
        except OSError:
            pass
        raise
