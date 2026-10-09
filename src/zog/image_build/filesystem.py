import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from .errors import ImageBuildError
from .metadata import identity, relative


def digest(path):
    with Path(path).open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
        return result.hexdigest()


def inventory(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ImageBuildError(f"not a real root directory: {root}")
    records = []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        record = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(mode)}
        if stat.S_ISLNK(mode):
            record.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISDIR(mode):
            record.update(kind="directory")
        elif stat.S_ISREG(mode):
            record.update(kind="file", sha256=digest(path))
        else:
            raise ImageBuildError(f"unsupported output file type: {path}")
        if mode & (stat.S_ISUID | stat.S_ISGID):
            raise ImageBuildError(
                f"set-id output requires future explicit support: {path}"
            )
        records.append(record)
    return records


def merge(source, destination, *, preserve_existing_directories=False, compose_info=False, copy_file=None):
    """Merge into a caller-owned staging tree, restoring directory modes on exit.

    Build dependency overlays keep the toolchain's shared directory modes. Final
    composition still rejects differing shared modes. Files never overwrite and
    destination symlinks are never traversed.
    """
    source, destination = Path(source), Path(destination)
    if destination.is_symlink():
        raise ImageBuildError("merge destination is a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    restore = {}

    def writable(directory, mode):
        if mode & 0o700 != 0o700:
            restore[directory] = mode
            directory.chmod(mode | 0o700)

    try:
        writable(destination, stat.S_IMODE(destination.stat().st_mode))
        for record in inventory(source):
            name = relative(record["path"])
            target = destination / name
            for parent in target.relative_to(destination).parents:
                if parent != Path(".") and (destination / parent).is_symlink():
                    raise ImageBuildError(f"output parent is a symlink: {name}")
            if compose_info and name == 'usr/share/info/dir':
                from .info_index import compose
                if record['kind'] != 'file' or target.is_symlink() or (target.exists() and not target.is_file()):
                    raise ImageBuildError('Info directory must be a regular file')
                contributions = [target.read_text()] if target.exists() else []
                combined = compose(*contributions, (source / name).read_text())
                target.parent.mkdir(parents=True, exist_ok=True)
                # This is a caller-owned disposable staging root, never an input.
                if target.exists(): target.unlink()
                target.write_text(combined); target.chmod(0o644)
                continue
            if target.exists() or target.is_symlink():
                if record["kind"] == "directory" and target.is_dir() and not target.is_symlink():
                    mode = stat.S_IMODE(target.stat().st_mode)
                    if not preserve_existing_directories and mode != record["mode"]:
                        raise ImageBuildError(f"directory mode conflict: {name}")
                    writable(target, mode)
                    continue
                raise ImageBuildError(f"output ownership conflict: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if record["kind"] == "directory":
                target.mkdir(mode=record["mode"] | 0o700)
                target.chmod(record["mode"] | 0o700)
                restore[target] = record["mode"]
            elif record["kind"] == "symlink":
                target.symlink_to(record["target"])
            else:
                (copy_file or shutil.copy2)(source / name, target)
    finally:
        for directory, mode in sorted(restore.items(), key=lambda item: len(item[0].parts), reverse=True):
            directory.chmod(mode)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory(path):
    path = Path(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        sync_directory(directory)
        sync_directory(directory.parent)


def write_json(path, value):
    path = Path(path)
    ensure_directory(path.parent)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_tree(path):
    for entry in Path(path).rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            with entry.open("rb") as stream:
                os.fsync(stream.fileno())
    for entry in sorted(
        (p for p in Path(path).rglob("*") if p.is_dir() and not p.is_symlink()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        sync_directory(entry)
    sync_directory(path)


def discard_staging(path):
    """Remove an unregistered caller-owned partial assembly, without following links."""
    path = Path(path)
    if path.is_symlink():
        path.unlink()
        return
    def writable_tree(directory):
        directory.chmod(stat.S_IMODE(directory.stat().st_mode) | 0o700)
        for child in directory.iterdir():
            if not child.is_symlink() and child.is_dir():
                writable_tree(child)
    writable_tree(path)
    shutil.rmtree(path)
    sync_directory(path.parent)
