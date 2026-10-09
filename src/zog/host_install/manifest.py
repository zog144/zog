"""Strict, local-only artifact contract. Hashes establish integrity, not trust."""
import hashlib
import json
import re
import uuid
from pathlib import PurePosixPath

from . import InstallError

MIB = 1024 * 1024
ROLES = ("ESP", "HOST-A", "HOST-B", "STATE", "APPLICATIONS")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise InstallError(message)


def keys(value, expected, where):
    require(isinstance(value, dict) and set(value) == set(expected.split()),
            f"invalid fields in {where}")


def integer(value, minimum, where):
    require(type(value) is int and value >= minimum, f"invalid {where}")


def nonempty(value, where):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 1024,
            f"invalid {where}")


def identifier(value, where):
    try:
        require(isinstance(value, str) and str(uuid.UUID(value)) == value and
                uuid.UUID(value).int != 0, f"invalid {where}")
    except (ValueError, AttributeError):
        raise InstallError(f"invalid {where}") from None


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return validate(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError) as exc:
        raise InstallError(f"invalid manifest JSON: {exc}") from None


def validate(m):
    keys(m, "schema generation architecture boot artifacts layout runtime", "manifest")
    require(type(m["schema"]) is int and m["schema"] == 1, "unsupported manifest schema")
    nonempty(m["generation"], "generation")
    require(m["architecture"] == "x86_64", "first pass supports x86_64 only")
    b = m["boot"]
    keys(b, "kind provider release kernel_release components root_partuuid root_argument root_read_only", "boot")
    require(b["kind"] == "foreign" and b["provider"] == "amazon-linux-2023",
            "only the foreign Amazon Linux 2023 boot provider is supported")
    for key in ("release", "kernel_release"):
        nonempty(b[key], key)
    require(isinstance(b["components"], dict) and set(b["components"]) ==
            {"kernel", "initramfs", "modules", "efi", "configuration"},
            "complete matching boot-set provenance is required")
    for role, value in b["components"].items():
        nonempty(value, f"boot component provenance: {role}")
    identifier(b["root_partuuid"], "boot root PARTUUID")
    require(b["root_argument"] == f"root=PARTUUID={b['root_partuuid']}" and
            b["root_read_only"] is True, "boot must bind HOST-A by PARTUUID with read-only root")
    keys(m["artifacts"], "rootfs esp", "artifacts")
    for name, a in m["artifacts"].items():
        keys(a, "path bytes sha256 format", name)
        nonempty(a["path"], f"{name} path")
        p = PurePosixPath(a["path"])
        require(not p.is_absolute() and ".." not in p.parts and str(p) == a["path"]
                and "\\" not in a["path"], "artifact paths must be normalized relative paths")
        integer(a["bytes"], 1, f"{name} size")
        require(isinstance(a["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", a["sha256"]),
                f"invalid {name} SHA-256")
        require(a["format"] == ("ext4" if name == "rootfs" else "fat32"),
                f"unsupported {name} format")
    keys(m["layout"], "disk_guid partitions", "layout")
    identifier(m["layout"]["disk_guid"], "disk GUID")
    parts = m["layout"]["partitions"]
    require(isinstance(parts, list) and len(parts) == 5, "exactly five partitions are required")
    ids = [m["layout"]["disk_guid"]]
    for role, p in zip(ROLES, parts):
        keys(p, "role mib partuuid filesystem_uuid", role)
        require(p["role"] == role, "partition order must be ESP/HOST-A/HOST-B/STATE/APPLICATIONS")
        integer(p["mib"], 64, f"{role} MiB")
        identifier(p["partuuid"], f"{role} PARTUUID")
        ids.append(p["partuuid"])
        if role == "ESP":
            require(p["filesystem_uuid"] is None, "ESP filesystem ID belongs to boot artifact")
        else:
            identifier(p["filesystem_uuid"], f"{role} filesystem UUID")
            ids.append(p["filesystem_uuid"])
    require(len(ids) == len(set(ids)), "disk, partition and filesystem UUIDs must be distinct")
    require(parts[1]["partuuid"] == b["root_partuuid"], "boot root PARTUUID is not HOST-A")
    require(parts[1]["mib"] == parts[2]["mib"], "HOST-A and HOST-B must have equal capacity")
    for name, index in (("esp", 0), ("rootfs", 1)):
        require(m["artifacts"][name]["bytes"] == parts[index]["mib"] * MIB,
                f"{name} image must exactly fill its partition")
    keys(m["runtime"], "state_mount applications_mount host_specific_identity", "runtime")
    require(m["runtime"] == {"state_mount": "/state", "applications_mount": "/applications",
                              "host_specific_identity": "first-boot"}, "unsupported runtime contract")
    return m
