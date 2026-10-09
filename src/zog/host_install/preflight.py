"""Read-only Linux topology checks. A passing report never enables device writes.

Only simple whole-disk targets are accepted for planning. Unknown root topology,
holders, swap, mounts and duplicate stable identifiers fail closed.
"""
import json
import os
import subprocess
from pathlib import Path

from .manifest import digest, require


def assess(snapshot, target, expected_identity, required_bytes):
    require(isinstance(snapshot, dict) and snapshot.get("schema") == 1,
            "unsupported inventory")
    require(snapshot.get("complete") is True, "incomplete block-device inventory")
    nodes = snapshot.get("devices", [])
    require(isinstance(nodes, list) and nodes, "no block-device inventory")
    indexed = {}
    for n in nodes:
        require(isinstance(n, dict) and set(n) == {"path", "devno", "type", "size", "read_only",
                "identity", "parents", "mounts", "holders"}, "invalid device inventory fields")
        require(n["path"] not in indexed, "duplicate device path")
        indexed[n["path"]] = n
        require(type(n["size"]) is int and n["size"] > 0 and type(n["read_only"]) is bool,
                "invalid device size or read-only flag")
        require(all(isinstance(n[k], list) for k in ("parents", "mounts", "holders")),
                "invalid device relationships")
    require(target in indexed, "explicit target absent from inventory")
    require(all(parent in indexed for n in nodes for parent in n["parents"]),
            "unresolved parent device")
    roots = snapshot.get("root_devnos")
    require(isinstance(roots, list) and roots and all(isinstance(x, str) for x in roots),
            "running root backing device is unknown")
    root_nodes = {n["path"] for n in nodes if n["devno"] in roots}
    require(all(any(n["devno"] == r for n in nodes) for r in roots),
            "running root backing topology is unresolved")
    def ancestors(paths):
        result = set()
        def visit(path, active):
            require(path not in active, "cyclic block-device topology")
            if path in result:
                return
            for parent in indexed[path]["parents"]:
                visit(parent, active | {path})
            result.add(path)
        for path in paths:
            visit(path, set())
        return result
    ancestors(indexed)  # Reject cycles even outside the selected target.
    root_backing = ancestors(root_nodes)
    require(target not in root_backing, "target contains the running root")
    node = indexed[target]
    require(node["type"] == "disk" and not node["parents"], "target must be a whole physical disk")
    require(isinstance(expected_identity, str) and expected_identity.strip() and
            node["identity"] == expected_identity, "stable target identity missing or mismatched")
    require(sum(n["identity"] == expected_identity for n in nodes) == 1, "ambiguous target identity")
    descendants = [n for n in nodes if target in ancestors([n["path"]])]
    require(not any(n["mounts"] for n in descendants), "target or descendant is mounted/in swap")
    require(not any(n["holders"] for n in descendants), "target has active device holders")
    require(not any(n["read_only"] for n in descendants), "target is read-only")
    require(node["size"] >= required_bytes, "target is too small")
    binding = {k: node[k] for k in ("identity", "size", "devno", "path")}
    return {"status": "planning-only", "device_writes_enabled": False, "target": binding,
            "inventory_sha256": digest(snapshot), "running_root_backing": sorted(root_backing)}


def collect():
    """Collect current-namespace evidence; unsupported/container roots are rejected."""
    result = subprocess.run(["lsblk", "--json", "--bytes", "--paths", "--output",
                             "NAME,MAJ:MIN,TYPE,SIZE,RO,SERIAL,WWN,PKNAME,MOUNTPOINTS"],
                            check=True, capture_output=True, text=True)
    source = json.loads(result.stdout)["blockdevices"]
    merged = {}
    def walk(items, parent=None):
        for item in items:
            path = item["name"]
            entry = merged.setdefault(path, dict(path=path, devno=item["maj:min"], type=item["type"],
                size=int(item["size"]), read_only=bool(item["ro"]),
                identity=("wwn:" + item["wwn"].strip()) if item.get("wwn") else
                         ("serial:" + item["serial"].strip()) if item.get("serial") else None,
                parents=[], mounts=[x for x in item.get("mountpoints", []) if x], holders=[]))
            pk = item.get("pkname") or parent
            if pk and pk not in entry["parents"]:
                entry["parents"].append(pk)
            holder_dir = Path("/sys/dev/block") / entry["devno"] / "holders"
            require(holder_dir.is_dir(), "sysfs holder evidence unavailable")
            entry["holders"] = sorted(x.name for x in holder_dir.iterdir())
            walk(item.get("children", []), path)
    walk(source)
    root = subprocess.run(["findmnt", "--json", "--target", "/", "--output", "MAJ:MIN,FSTYPE"],
                          check=True, capture_output=True, text=True)
    root_rows = json.loads(root.stdout)["filesystems"]
    require(len(root_rows) == 1 and root_rows[0]["fstype"] not in ("overlay", "tmpfs", "btrfs", "zfs"),
            "root filesystem backing topology is unsupported")
    # lsblk MOUNTPOINTS includes active block swap; file swap must be accounted for as well.
    swaps = Path("/proc/swaps").read_text().splitlines()[1:]
    for row in swaps:
        path = row.split()[0]
        if path in merged:
            merged[path]["mounts"].append("[SWAP]")
        else:
            st = os.stat(path)
            devno = f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
            matches = [n for n in merged.values() if n["devno"] == devno]
            require(bool(matches), "swap backing device unknown")
            for n in matches:
                n["mounts"].append("[SWAPFILE]")
    return {"schema": 1, "complete": True, "devices": list(merged.values()),
            "root_devnos": [root_rows[0]["maj:min"]]}
