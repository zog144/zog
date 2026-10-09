"""Assemble only the exact reviewed companion sources; never ship a working tree."""
import hashlib
from importlib import resources
import io
import json
import os
from pathlib import Path, PurePosixPath
import zipfile

def payload(source=None):
    package = resources.files(__package__)
    selected = source or os.environ.get("HOST_DEPLOY_SOURCE_DIRECTORY")
    if not selected:
        raise ValueError("Pinned companion source directory required; pass --source DIRECTORY or set HOST_DEPLOY_SOURCE_DIRECTORY")
    root = Path(selected).absolute()
    pins = json.loads(package.joinpath("beacon_sources.json").read_text())
    files = {}
    for name, pin in pins["packages"].items():
        for relative, digest in pin["files"].items():
            parts = PurePosixPath(relative).parts
            if relative.startswith("/") or ".." in parts:
                raise ValueError("Unsafe beacon source path")
            path = root / name / relative
            # Reject substituted symlink sources rather than following them.
            if any(p.is_symlink() for p in [path, *path.parents]):
                raise ValueError("Beacon source must not traverse symbolic links")
            try:
                data = path.read_bytes()
            except OSError:
                raise ValueError("Missing pinned beacon source; retrieve host-deploy dependencies and pass --source DIRECTORY") from None
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Beacon source differs from pinned commit: " + name + "/" + relative)
            files[name + "/" + relative] = data
    files["beacon-source-versions.json"] = json.dumps(pins, sort_keys=True).encode()
    files["beacon_install.py"] = package.joinpath("beacon_install.py").read_bytes()
    files["requirements-security-tested.txt"] = package.joinpath("beacon_installation").joinpath("requirements-security-tested.txt").read_bytes()
    files["deployment/signed-identity/host-discover.service"] = files["host-discover/deployment/host-discover.service"]
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return result.getvalue()
