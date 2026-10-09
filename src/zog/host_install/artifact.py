"""Consume image-build artifact v1 through its canonical verifier.

The upstream package is an optional integration dependency. We deliberately do not
reimplement its canonical identity or generation inventory protocol. This pass
stages only; readiness.installable=false never becomes permission to install.
"""
import importlib
import os
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath

from . import InstallError
from .image import open_regular, record, sync_dir
from .manifest import require


def upstream_verify(directory, expected_id):
    try:
        module = importlib.import_module("zog.image_build.host_export")
        errors = importlib.import_module("zog.image_build.errors")
    except ImportError:
        raise InstallError("zog.image_build.host_export is required; supply the reviewed image-build source") from None
    try:
        return module.verify(directory, expected_id)
    except errors.ImageBuildError as exc:
        raise InstallError(f"image-build verification failed: {exc}") from exc


def extract(source, destination, maximum_bytes):
    """Extract a verified USTAR inventory without following any archive symlink.

    Caller-owned fresh directory. Full archive validation precedes filesystem
    writes. All directories/files precede symlinks; modes are applied last.
    Absolute symlink targets are kept as installed-root semantics, never followed.
    """
    require(type(maximum_bytes) is int and maximum_bytes >= 0, "invalid extraction size bound")
    destination = Path(destination)
    require(not destination.exists() and not destination.is_symlink(), "extraction destination must be new")
    with open_regular(source) as inp, tarfile.open(fileobj=inp, mode="r:") as archive:
        entries = {}
        total = 0
        for member in archive:
            name = member.name.rstrip("/") if member.isdir() else member.name
            p = PurePosixPath(name)
            require(name and not p.is_absolute() and ".." not in p.parts and
                    str(p) == name and "\\" not in name, "unsafe archive path")
            require(name not in entries, "duplicate archive member")
            require(member.isdir() or member.isreg() or member.issym(), "unsupported archive member kind")
            require(member.uid == member.gid == 0 and member.mode & ~0o1777 == 0,
                    "unsupported archive ownership or mode")
            require(not member.pax_headers, "extended archive metadata is unsupported")
            require(member.size >= 0 and (member.isreg() or member.size == 0), "invalid archive member size")
            if member.issym():
                require(bool(member.linkname) and "\0" not in member.linkname, "invalid symlink target")
            total += member.size
            require(total <= maximum_bytes, "archive exceeds extraction size bound")
            require(len(entries) < 1_000_000, "archive entry limit exceeded")
            entries[name] = member
        for name in entries:
            for parent in PurePosixPath(name).parents:
                if str(parent) != ".":
                    require(str(parent) in entries and entries[str(parent)].isdir(),
                            "archive parent is absent or not a directory")
        destination.mkdir(mode=0o700)
        try:
            for name, member in sorted(entries.items(), key=lambda kv: (len(PurePosixPath(kv[0]).parts), kv[0])):
                if member.isdir():
                    (destination / name).mkdir(mode=0o700)
            for name, member in entries.items():
                if member.isreg():
                    with archive.extractfile(member) as source_file, (destination / name).open("xb") as target:
                        shutil.copyfileobj(source_file, target, 1024 * 1024)
                        target.flush()
                        os.fsync(target.fileno())
            for name, member in entries.items():
                if member.issym():
                    os.symlink(member.linkname, destination / name)
            # Do not chown the host-side tree. mkfs.ext4 -d's source ownership is
            # only supported under uid/gid 0 in the later filesystem assembly.
            for name, member in sorted(entries.items(), reverse=True):
                if not member.issym():
                    os.chmod(destination / name, member.mode)
                    if member.isdir():
                        sync_dir(destination / name)
            os.chmod(destination, 0o755)
            sync_dir(destination)
            sync_dir(destination.parent)
        except BaseException:
            # Keep incomplete output as evidence, never follow links to clean it.
            raise
    return {"entries": len(entries), "regular_file_bytes": total,
            "ownership_policy": "all-root-v1", "host_tree_ownership": "current-user"}


def stage(directory, expected_id, destination):
    """Snapshot verified bundle then extract it into a new operation directory."""
    source = Path(directory)
    initial = upstream_verify(source, expected_id)
    require(initial.get("schema") == 1 and initial.get("kind") == "host-install-artifact" and
            initial.get("ownership_policy") == "all-root-v1", "unsupported artifact contract")
    require(initial.get("artifact_id") == expected_id, "upstream verifier returned a different artifact")
    require(isinstance(initial.get("readiness"), dict) and
            initial["readiness"].get("installable") is False,
            "artifact-v1 must retain installable=false")
    op = Path(destination).absolute()
    op.mkdir(mode=0o700)
    sync_dir(op.parent)
    status = {"schema": 1, "artifact_id": expected_id, "status": "snapshotting",
              "installable": False, "source_readiness": initial["readiness"],
              "source_security": initial["security"], "device_writes_enabled": False}
    record(op / "staging.json", status)
    try:
        bundle = op / "bundle"
        bundle.mkdir(mode=0o700)
        names = ["manifest.json", "rootfs.tar"]
        if initial.get("boot_bundle") is not None:
            names.append("boot.tar")
        for name in names:
            with open_regular(source / name) as src, (bundle / name).open("xb") as target:
                shutil.copyfileobj(src, target, 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        sync_dir(bundle)
        m = upstream_verify(bundle, expected_id)
        require(m == initial, "artifact changed during snapshot")
        status["status"] = "extracting"
        record(op / "staging.json", status)
        status["rootfs"] = extract(bundle / "rootfs.tar", op / "rootfs", m["rootfs"]["bytes"])
        if m.get("boot_bundle") is not None:
            status["boot"] = extract(bundle / "boot.tar", op / "boot",
                                     m["boot_bundle"]["payload"]["bytes"])
        # Reverify the snapshot after extraction. Output tree verification below
        # compares every member's mode, bytes and link against these same archives.
        upstream_verify(bundle, expected_id)
        verify_tree(bundle / "rootfs.tar", op / "rootfs")
        if m.get("boot_bundle") is not None:
            verify_tree(bundle / "boot.tar", op / "boot")
        status["status"] = "staged-for-offline-tests"
        status["blockers"] = ["host mount mapping and service composition unresolved",
                              "EFI/bootloader configuration absent from artifact-v1 contract",
                              "physical-device writer disabled in host-install 0.1.0",
                              "first boot and authenticated enrollment not tested"]
        record(op / "staging.json", status)
        return status
    except BaseException as exc:
        status.update(status="incomplete", error=f"{type(exc).__name__}: {exc}")
        try:
            record(op / "staging.json", status)
        except OSError:
            pass
        raise


def verify_tree(archive_path, root):
    """Compare extraction to archive using lstat and no-follow file opens."""
    root = Path(root)
    st = root.lstat()
    require(stat.S_ISDIR(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o755,
            "installed root directory mode differs")
    with open_regular(archive_path) as source, tarfile.open(fileobj=source, mode="r:") as archive:
        members = {m.name.rstrip("/") if m.isdir() else m.name: m for m in archive}
        actual = set()
        for directory, subdirs, files in os.walk(root, followlinks=False):
            for name in subdirs + files:
                actual.add(str((Path(directory) / name).relative_to(root)))
        require(actual == set(members), "extracted inventory differs")
        for name, member in members.items():
            path = root / name
            # Every ancestor was created and verified as a real directory.
            for parent in path.parents:
                if parent == root:
                    break
                require(stat.S_ISDIR(parent.lstat().st_mode), "extracted symlink ancestor")
            st = path.lstat()
            if member.issym():
                require(stat.S_ISLNK(st.st_mode) and os.readlink(path) == member.linkname,
                        "extracted symlink differs")
            else:
                require(stat.S_IMODE(st.st_mode) == member.mode, "extracted mode differs")
                if member.isdir():
                    require(stat.S_ISDIR(st.st_mode), "extracted directory differs")
                else:
                    require(stat.S_ISREG(st.st_mode) and st.st_size == member.size,
                            "extracted file kind/size differs")
                    with open_regular(path) as actual_file, archive.extractfile(member) as expected:
                        while chunk := expected.read(1024 * 1024):
                            require(actual_file.read(len(chunk)) == chunk, "extracted file bytes differ")
