"""Synthetic fixtures, deliberately not boot candidates."""
import hashlib
import json
import struct
import subprocess
import uuid
from pathlib import Path

from zog.host_install.manifest import MIB, ROLES


def manifest():
    partitions = [dict(role=role, mib=64, partuuid=str(uuid.uuid4()),
                       filesystem_uuid=None if role == "ESP" else str(uuid.uuid4())) for role in ROLES]
    return {"schema": 1, "generation": "synthetic-test-only", "architecture": "x86_64",
        "boot": {"kind": "foreign", "provider": "amazon-linux-2023", "release": "fixture",
                 "kernel_release": "fixture-not-a-kernel", "components": {
                     k: "synthetic-placeholder-not-bootable" for k in
                     ("kernel", "initramfs", "modules", "efi", "configuration")},
                 "root_partuuid": partitions[1]["partuuid"],
                 "root_argument": "root=PARTUUID=" + partitions[1]["partuuid"], "root_read_only": True},
        "artifacts": {k: {"path": k + ".img", "bytes": 64 * MIB, "sha256": "0" * 64,
                          "format": fmt} for k, fmt in (("esp", "fat32"), ("rootfs", "ext4"))},
        "layout": {"disk_guid": str(uuid.uuid4()), "partitions": partitions},
        "runtime": {"state_mount": "/state", "applications_mount": "/applications",
                    "host_specific_identity": "first-boot"}}


def fat_fixture(path):
    """Minimal empty FAT32 test volume; contains no EFI binaries/configuration."""
    sectors, reserved, fat_sectors = 131072, 32, 1009
    boot = bytearray(512)
    boot[:11] = b"\xeb\x58\x90TESTONLY"
    struct.pack_into("<HBHBHHBHHHII", boot, 11, 512, 1, reserved, 2, 0, 0, 0xF8,
                     0, 63, 255, 0, sectors)
    struct.pack_into("<IHHIHH", boot, 36, fat_sectors, 0, 0, 2, 1, 6)
    boot[64] = 0x80
    boot[66] = 0x29
    struct.pack_into("<I", boot, 67, 0x12345678)
    boot[71:82] = b"TEST-ESP   "
    boot[82:90] = b"FAT32   "
    boot[510:512] = b"\x55\xaa"
    info = bytearray(512)
    struct.pack_into("<I", info, 0, 0x41615252)
    struct.pack_into("<III", info, 484, 0x61417272, 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into("<I", info, 508, 0xAA550000)
    with path.open("xb") as out:
        out.truncate(64 * MIB)
        out.write(boot)
        out.write(info)
        out.seek(6 * 512)
        out.write(boot)
        out.write(info)
        for start in (reserved, reserved + fat_sectors):
            out.seek(start * 512)
            out.write(struct.pack("<III", 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFFF))


def artifacts(directory):
    directory = Path(directory)
    directory.mkdir()
    m = manifest()
    root = directory / "rootfs.img"
    with root.open("xb") as out:
        out.truncate(64 * MIB)
    subprocess.run(["mkfs.ext4", "-q", "-F", "-U", m["layout"]["partitions"][1]["filesystem_uuid"],
                    "-E", "lazy_itable_init=0,lazy_journal_init=0", str(root)], check=True)
    fat_fixture(directory / "esp.img")
    for name, a in m["artifacts"].items():
        with (directory / a["path"]).open("rb") as source:
            a["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    (directory / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    return m


def inventory():
    def node(path, devno, kind, parents, mounts, identity=None):
        return dict(path=path, devno=devno, type=kind, size=1024 * MIB, read_only=False,
                    parents=parents, mounts=mounts, identity=identity, holders=[])
    return {"schema": 1, "complete": True, "root_devnos": ["253:0"], "devices": [
        node("/dev/rootdisk", "8:0", "disk", [], [], "serial:root"),
        node("/dev/rootpart", "8:1", "part", ["/dev/rootdisk"], []),
        node("/dev/mapper/root", "253:0", "lvm", ["/dev/rootpart"], ["/"]),
        node("/dev/target", "8:16", "disk", [], [], "serial:target"),
        node("/dev/target1", "8:17", "part", ["/dev/target"], [])]}
