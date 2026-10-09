"""Host RPM installation is explicit developer preparation, never normal execution."""

import argparse
import json
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from ..errors import ImageBuildError
from ..filesystem import inventory, write_json

BASE_PACKAGES = (
    "gcc",
    "gcc-c++",
    "binutils",
    "bison",
    "m4",
    "texinfo",
    "glibc-devel",
    "glibc-headers",
    "make",
    "cmake",
    "bash",
    "coreutils",
    "findutils",
    "diffutils",
    "grep",
    "sed",
    "gawk",
    "patch",
    "tar",
    "gzip",
    "bzip2",
    "xz",
    "file",
    "which",
    "perl",
    "python3",
)


def detect(path="/etc/os-release"):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            words = shlex.split(value)
            values[key] = words[0] if words else ""
    system, version = values.get("ID"), values.get("VERSION_ID")
    if system == "amzn" and version == "2023":
        return {
            "id": "amazon-linux-2023",
            "manager": "dnf",
            "release": values,
            "architecture": platform.machine(),
        }
    if system == "amzn" and version == "2":
        return {
            "id": "amazon-linux-2",
            "manager": "yum",
            "release": values,
            "architecture": platform.machine(),
        }
    if system == "fedora":
        return {
            "id": "fedora",
            "manager": "dnf",
            "release": values,
            "architecture": platform.machine(),
        }
    raise ImageBuildError(f"unsupported bootstrap host: {system} {version}")


def install_command(profile, extra=()):
    return [profile["manager"], "-y", "install", *BASE_PACKAGES, *extra]


def assemble(paths, destination, *, host_root=Path("/")):
    """Copy a reviewed file list, preserving symlinks and collecting their targets.

    Parent symlinks are normalized to real directories in the assembled root.
    Shared-library and compiler-support closure must be included by the author.
    """
    destination, host_root = Path(destination), Path(host_root).resolve()
    if destination.exists():
        raise ImageBuildError("bootstrap destination must be new")
    destination.mkdir(parents=True)
    pending = list(paths)
    seen = set()
    while pending:
        name = pending.pop()
        if (
            not isinstance(name, str)
            or not name.startswith("/")
            or ".." in Path(name).parts
        ):
            raise ImageBuildError(f"invalid host inventory path: {name!r}")
        if name in seen:
            continue
        seen.add(name)
        source = host_root / name.lstrip("/")
        try:
            canonical_parent = source.parent.resolve(strict=True).relative_to(host_root)
        except (OSError, ValueError) as error:
            raise ImageBuildError(f"host path escapes or is missing: {name}") from error
        target = destination / canonical_parent / source.name
        if source.is_symlink():
            link = source.readlink()
            resolved = (
                (host_root / str(link).lstrip("/"))
                if link.is_absolute()
                else source.parent / link
            )
            try:
                canonical = resolved.resolve(strict=True).relative_to(host_root)
            except (OSError, ValueError) as error:
                raise ImageBuildError(
                    f"host symlink escapes or is missing: {name}"
                ) from error
            pending.append("/" + canonical.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            # Use canonical in-root target, including chains and relative targets.
            target.symlink_to("/" + canonical.as_posix())
        elif source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            pending.extend(name.rstrip("/") + "/" + p.name for p in source.iterdir())
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            raise ImageBuildError(f"missing/unsupported host bootstrap input: {name}")
    return inventory(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        action="store_true",
        help="execute host package installation; default prints plan",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        help="JSON array of explicitly reviewed absolute host paths",
    )
    parser.add_argument("--destination", type=Path)
    arguments = parser.parse_args()
    profile = detect()
    command = install_command(profile)
    print(json.dumps({"host": profile, "install_command": command}, indent=2))
    if arguments.install:
        subprocess.run(command, check=True)
    if arguments.inventory:
        if not arguments.destination:
            parser.error("--inventory requires --destination")
        files = assemble(
            json.loads(arguments.inventory.read_text()), arguments.destination
        )
        provenance = {
            "host": profile,
            "files": files,
            "installed_rpms": subprocess.check_output(
                ["rpm", "-qa", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n"],
                text=True,
            ).splitlines(),
        }
        write_json(
            arguments.destination.with_name(
                arguments.destination.name + "-provenance.json"
            ),
            provenance,
        )


if __name__ == "__main__":
    main()
