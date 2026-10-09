"""Durable immutable application-software artifact publication.

Application software is distinct from both a base rootfs generation and persistent
application data.  This store owns content-addressed software trees that a trusted
controller can later resolve by artifact ID and mount read-only below /applications.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit

from .errors import ImageBuildError
from .filesystem import (
    discard_staging,
    ensure_directory,
    inventory,
    sync_directory,
    sync_tree,
    write_json,
)

SCHEMA = 1
KIND = "application-software"
MOUNT_CONTRACT = "applications-v1"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_OPERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SECRET_KEYS = ("secret", "password", "token", "credential", "private_key", "private-key")


@dataclass(frozen=True)
class ApplicationSoftwareOperation:
    operation: str
    root: Path
    intent: dict
    frozen: bool = False
    artifact: str | None = None


@dataclass(frozen=True)
class ApplicationSoftwareArtifact:
    artifact: str
    root: Path
    manifest: dict
    reused: bool = False


def _copy(value):
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as error:
        raise ImageBuildError("application software metadata must be JSON data") from error


def _text(value, label, *, maximum=512):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ImageBuildError(f"invalid application software {label}")
    return value


def _relative(value, label):
    value = _text(value, label, maximum=1024)
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise ImageBuildError(f"invalid application software {label}")
    return path.as_posix()


def _reject_secrets(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ImageBuildError("application software metadata keys must be strings")
            normalized = key.lower().replace("-", "_")
            if any(marker in normalized for marker in _SECRET_KEYS):
                location = ".".join((*path, key))
                raise ImageBuildError(
                    f"application software metadata must not contain credentials: {location}"
                )
            _reject_secrets(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, (*path, str(index)))


def _source(record):
    if not isinstance(record, dict) or set(record) not in (
        {"url", "sha256"},
        {"name", "url", "sha256"},
    ):
        raise ImageBuildError("invalid application software source identity")
    result = dict(record)
    if "name" in result:
        result["name"] = _text(result["name"], "source name", maximum=256)
    url = _text(result["url"], "source URL", maximum=4096)
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "file", "recipe"}:
        raise ImageBuildError("unsupported application software source URL")
    if parsed.username is not None or parsed.password is not None:
        raise ImageBuildError("application software source URL must not contain credentials")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower().replace("-", "_")
        if any(marker in normalized for marker in _SECRET_KEYS):
            raise ImageBuildError(
                "application software source URL must not contain credential query fields"
            )
    digest = result["sha256"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ImageBuildError("invalid application software source SHA-256")
    return result


def compatibility(value):
    """Validate/canonicalize an application/rootfs compatibility descriptor."""
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "mount_contract",
        "architecture",
        "python",
        "libraries",
    }:
        raise ImageBuildError("invalid application software compatibility descriptor")
    if value["schema"] != SCHEMA or value["mount_contract"] != MOUNT_CONTRACT:
        raise ImageBuildError("unsupported application software compatibility contract")
    architecture = _text(value["architecture"], "architecture", maximum=128)
    python = value["python"]
    if python is not None:
        if not isinstance(python, dict) or set(python) != {
            "implementation",
            "version",
            "soabi",
        }:
            raise ImageBuildError("invalid application software Python compatibility")
        python = {
            "implementation": _text(
                python["implementation"], "Python implementation", maximum=64
            ),
            "version": _text(python["version"], "Python version", maximum=64),
            "soabi": _text(python["soabi"], "Python SOABI", maximum=256),
        }
    libraries = value["libraries"]
    if (
        not isinstance(libraries, list)
        or any(not isinstance(item, str) for item in libraries)
    ):
        raise ImageBuildError("invalid application software library compatibility")
    libraries = sorted(
        {
            _text(item, "required library", maximum=256)
            for item in libraries
        }
    )
    return {
        "schema": SCHEMA,
        "mount_contract": MOUNT_CONTRACT,
        "architecture": architecture,
        "python": python,
        "libraries": libraries,
    }


def compatibility_gaps(required, provided):
    """Return deterministic incompatibility reasons; an empty tuple means compatible."""
    required = compatibility(required)
    provided = compatibility(provided)
    gaps = []
    if required["architecture"] != provided["architecture"]:
        gaps.append(
            f"architecture:{required['architecture']}!={provided['architecture']}"
        )
    if required["python"] is not None and required["python"] != provided["python"]:
        gaps.append("python")
    missing = sorted(set(required["libraries"]) - set(provided["libraries"]))
    gaps.extend("library:" + library for library in missing)
    return tuple(gaps)


def require_compatible(required, provided):
    gaps = compatibility_gaps(required, provided)
    if gaps:
        raise ImageBuildError(
            "application software is incompatible with rootfs: " + ", ".join(gaps)
        )


def _safe_links(records):
    for record in records:
        if record["kind"] != "symlink":
            continue
        target = PurePosixPath(record["target"])
        if target.is_absolute():
            raise ImageBuildError(
                f"application software symlink is absolute: {record['path']}"
            )
        parent = PurePosixPath(record["path"]).parent
        parts = []
        for part in (parent / target).parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    raise ImageBuildError(
                        f"application software symlink escapes artifact: {record['path']}"
                    )
                parts.pop()
            else:
                parts.append(part)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _artifact_identity(manifest):
    payload = {key: value for key, value in manifest.items() if key != "artifact"}
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _artifact_hex(value):
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or not _SHA256.fullmatch(value[7:])
    ):
        raise ImageBuildError("invalid application software artifact identity")
    return value[7:]


def _intent(
    operation,
    *,
    application,
    revision,
    sources,
    compatibility_requirements,
    notices,
    provenance,
):
    if not isinstance(operation, str) or not _OPERATION.fullmatch(operation):
        raise ImageBuildError("invalid application software operation identity")
    if not isinstance(application, str) or not _NAME.fullmatch(application):
        raise ImageBuildError("invalid application software name")
    revision = _text(revision, "revision", maximum=512)
    if not isinstance(sources, (list, tuple)):
        raise ImageBuildError("application software sources must be a sequence")
    source_records = [_source(record) for record in sources]
    if len({_canonical(record) for record in source_records}) != len(source_records):
        raise ImageBuildError("duplicate application software source identity")
    if not isinstance(notices, (list, tuple)):
        raise ImageBuildError("application software notices must be a sequence")
    notice_paths = sorted({_relative(value, "notice path") for value in notices})
    if len(notice_paths) != len(notices):
        raise ImageBuildError("duplicate application software notice path")
    provenance = _copy(provenance or {})
    if not isinstance(provenance, dict):
        raise ImageBuildError("application software provenance must be an object")
    _reject_secrets(provenance)
    return {
        "schema": SCHEMA,
        "operation": operation,
        "application": application,
        "revision": revision,
        "sources": sorted(source_records, key=_canonical),
        "compatibility": compatibility(compatibility_requirements),
        "notices": notice_paths,
        "provenance": provenance,
    }


def read_artifact(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ImageBuildError(f"invalid application software artifact directory: {directory}")
    artifact = "sha256:" + directory.name
    _artifact_hex(artifact)
    manifest_path = directory / "manifest.json"
    root = directory / "root"
    if manifest_path.is_symlink() or root.is_symlink() or not root.is_dir():
        raise ImageBuildError("invalid application software artifact layout")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError, TypeError) as error:
        raise ImageBuildError("invalid application software manifest") from error
    required = {
        "schema",
        "kind",
        "artifact",
        "application",
        "revision",
        "architecture",
        "mount_contract",
        "sources",
        "compatibility",
        "notices",
        "provenance",
        "outputs",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or manifest.get("schema") != SCHEMA
        or manifest.get("kind") != KIND
        or manifest.get("artifact") != artifact
        or manifest.get("mount_contract") != MOUNT_CONTRACT
    ):
        raise ImageBuildError("unsupported application software manifest")
    if _artifact_identity(manifest) != artifact:
        raise ImageBuildError("application software manifest identity changed")
    expected_compatibility = compatibility(manifest["compatibility"])
    if (
        expected_compatibility != manifest["compatibility"]
        or manifest["architecture"] != expected_compatibility["architecture"]
    ):
        raise ImageBuildError("application software compatibility metadata changed")
    records = inventory(root)
    _safe_links(records)
    if records != manifest["outputs"]:
        raise ImageBuildError("application software installed files changed")
    files = {
        record["path"]: record
        for record in records
        if record["kind"] == "file"
    }
    for path in manifest["notices"]:
        if path not in files:
            raise ImageBuildError(
                f"application software notice is not a retained regular file: {path}"
            )
    return ApplicationSoftwareArtifact(artifact, root, manifest, True)


class ApplicationSoftwareStore:
    """Durable producer-side store for immutable application software."""

    def __init__(self, state_dir):
        self.state = Path(state_dir)
        self.root = self.state / "image-build" / "application-software"
        ensure_directory(self.state)
        ensure_directory(self.root / "operations")
        ensure_directory(self.root / "candidates")
        ensure_directory(self.root / "artifacts")

    @contextmanager
    def locked(self):
        with (self.state / "image-build.lock").open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _operation(self, operation):
        if not isinstance(operation, str) or not _OPERATION.fullmatch(operation):
            raise ImageBuildError("invalid application software operation identity")
        return self.root / "operations" / operation

    def begin(
        self,
        operation,
        *,
        application,
        revision,
        sources=(),
        compatibility_requirements,
        notices=(),
        provenance=None,
    ):
        intent = _intent(
            operation,
            application=application,
            revision=revision,
            sources=sources,
            compatibility_requirements=compatibility_requirements,
            notices=notices,
            provenance=provenance,
        )
        with self.locked():
            path = self._operation(operation)
            ensure_directory(path)
            intent_path = path / "intent.json"
            if intent_path.exists():
                try:
                    existing = json.loads(intent_path.read_text())
                except (OSError, ValueError, TypeError) as error:
                    raise ImageBuildError(
                        "invalid retained application software intent"
                    ) from error
                if existing != intent:
                    raise ImageBuildError(
                        "retained application software operation changed"
                    )
            else:
                write_json(intent_path, intent)
            result_path = path / "result.json"
            artifact = None
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text())
                    artifact = result["artifact"]
                except (OSError, ValueError, TypeError, KeyError) as error:
                    raise ImageBuildError(
                        "invalid retained application software result"
                    ) from error
                self.resolve(artifact)
            frozen = (path / "frozen.json").exists()
            root = path / "root"
            if artifact is None and not frozen:
                ensure_directory(root)
            return ApplicationSoftwareOperation(
                operation, root, intent, frozen=frozen, artifact=artifact
            )

    def _freeze(self, operation_path, intent):
        frozen_path = operation_path / "frozen.json"
        if frozen_path.exists():
            try:
                frozen = json.loads(frozen_path.read_text())
            except (OSError, ValueError, TypeError) as error:
                raise ImageBuildError(
                    "invalid frozen application software publication"
                ) from error
            if (
                not isinstance(frozen, dict)
                or set(frozen) != {"schema", "artifact", "manifest"}
                or frozen.get("schema") != SCHEMA
                or frozen.get("artifact") != frozen.get("manifest", {}).get("artifact")
                or _artifact_identity(frozen["manifest"]) != frozen["artifact"]
            ):
                raise ImageBuildError(
                    "frozen application software publication identity changed"
                )
            return frozen

        root = operation_path / "root"
        if root.is_symlink() or not root.is_dir():
            raise ImageBuildError("application software staging root is unavailable")
        sync_tree(root)
        outputs = inventory(root)
        _safe_links(outputs)
        files = {
            record["path"]: record
            for record in outputs
            if record["kind"] == "file"
        }
        for notice in intent["notices"]:
            if notice not in files:
                raise ImageBuildError(
                    f"application software notice is not a retained regular file: {notice}"
                )
        manifest = {
            "schema": SCHEMA,
            "kind": KIND,
            "artifact": "",
            "application": intent["application"],
            "revision": intent["revision"],
            "architecture": intent["compatibility"]["architecture"],
            "mount_contract": MOUNT_CONTRACT,
            "sources": intent["sources"],
            "compatibility": intent["compatibility"],
            "notices": intent["notices"],
            "provenance": intent["provenance"],
            "outputs": outputs,
        }
        manifest["artifact"] = _artifact_identity(manifest)
        frozen = {
            "schema": SCHEMA,
            "artifact": manifest["artifact"],
            "manifest": manifest,
        }
        write_json(frozen_path, frozen)
        return frozen

    def _candidate(self, operation, operation_path, frozen):
        candidate = self.root / "candidates" / operation
        root = operation_path / "root"
        candidate_root = candidate / "root"
        if candidate.is_symlink():
            raise ImageBuildError("application software candidate is a symlink")
        if not candidate.exists():
            ensure_directory(candidate)
        if not candidate_root.exists():
            if root.is_symlink() or not root.is_dir():
                raise ImageBuildError(
                    "application software frozen staging root is unavailable"
                )
            os.replace(root, candidate_root)
            sync_directory(operation_path)
            sync_directory(candidate)
        elif root.exists() or root.is_symlink():
            raise ImageBuildError(
                "application software has both staging and candidate roots"
            )
        if inventory(candidate_root) != frozen["manifest"]["outputs"]:
            raise ImageBuildError(
                "application software candidate differs from frozen inventory"
            )
        _safe_links(frozen["manifest"]["outputs"])
        manifest_path = candidate / "manifest.json"
        if manifest_path.exists():
            try:
                value = json.loads(manifest_path.read_text())
            except (OSError, ValueError, TypeError) as error:
                raise ImageBuildError(
                    "invalid application software candidate manifest"
                ) from error
            if value != frozen["manifest"]:
                raise ImageBuildError(
                    "application software candidate manifest differs"
                )
        else:
            write_json(manifest_path, frozen["manifest"])
        sync_tree(candidate)
        return candidate

    def finalize(self, operation):
        with self.locked():
            path = self._operation(operation)
            intent_path = path / "intent.json"
            if not intent_path.exists():
                raise ImageBuildError("unknown application software operation")
            try:
                intent = json.loads(intent_path.read_text())
            except (OSError, ValueError, TypeError) as error:
                raise ImageBuildError(
                    "invalid retained application software intent"
                ) from error

            result_path = path / "result.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text())
                    artifact = self.resolve(result["artifact"])
                except (OSError, ValueError, TypeError, KeyError) as error:
                    raise ImageBuildError(
                        "invalid retained application software result"
                    ) from error
                return ApplicationSoftwareArtifact(
                    artifact.artifact,
                    artifact.root,
                    artifact.manifest,
                    True,
                )

            frozen = self._freeze(path, intent)
            artifact_id = frozen["artifact"]
            target = self.root / "artifacts" / _artifact_hex(artifact_id)
            reused = target.exists()
            if reused:
                existing = read_artifact(target)
                if existing.manifest != frozen["manifest"]:
                    raise ImageBuildError(
                        "application software artifact identity collision"
                    )
                candidate = self.root / "candidates" / operation
                if candidate.exists():
                    candidate = self._candidate(operation, path, frozen)
                    discard_staging(candidate)
                elif (path / "root").exists():
                    if inventory(path / "root") != frozen["manifest"]["outputs"]:
                        raise ImageBuildError(
                            "application software staging root changed after freeze"
                        )
                    discard_staging(path / "root")
            else:
                candidate = self._candidate(operation, path, frozen)
                if target.exists():
                    raise ImageBuildError(
                        "application software artifact appeared during publication"
                    )
                os.replace(candidate, target)
                sync_directory(target.parent)
                existing = read_artifact(target)
                if existing.manifest != frozen["manifest"]:
                    raise ImageBuildError(
                        "published application software differs from frozen manifest"
                    )
            write_json(
                result_path,
                {
                    "schema": SCHEMA,
                    "operation": operation,
                    "artifact": artifact_id,
                },
            )
            resolved = self.resolve(artifact_id)
            return ApplicationSoftwareArtifact(
                resolved.artifact,
                resolved.root,
                resolved.manifest,
                reused,
            )

    def resolve(self, artifact):
        return read_artifact(
            self.root / "artifacts" / _artifact_hex(artifact)
        )

    def binding(self, artifact):
        """Resolve a caller-supplied ID into a controller-owned trusted binding."""
        value = self.resolve(artifact)
        return {
            "schema": SCHEMA,
            "artifact": value.artifact,
            "application": value.manifest["application"],
            "root": str(value.root.resolve()),
            "mount_contract": value.manifest["mount_contract"],
            "compatibility": value.manifest["compatibility"],
        }

    def require_compatible(self, artifact, rootfs_compatibility):
        value = self.resolve(artifact)
        require_compatible(
            value.manifest["compatibility"], rootfs_compatibility
        )
        return value


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    sub = parser.add_subparsers(dest="operation_name", required=True)

    begin = sub.add_parser("begin")
    begin.add_argument("operation")
    begin.add_argument("declaration", type=Path)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("operation")

    inspect = sub.add_parser("inspect")
    inspect.add_argument("artifact")

    binding = sub.add_parser("binding")
    binding.add_argument("artifact")

    args = parser.parse_args()
    store = ApplicationSoftwareStore(args.state_dir)
    if args.operation_name == "begin":
        try:
            declaration = json.loads(args.declaration.read_text())
        except (OSError, ValueError, TypeError) as error:
            raise SystemExit(f"invalid application software declaration: {error}")
        operation = store.begin(
            args.operation,
            application=declaration["application"],
            revision=declaration["revision"],
            sources=declaration.get("sources", []),
            compatibility_requirements=declaration["compatibility"],
            notices=declaration.get("notices", []),
            provenance=declaration.get("provenance", {}),
        )
        value = {
            "schema": SCHEMA,
            "operation": operation.operation,
            "root": str(operation.root),
            "frozen": operation.frozen,
            "artifact": operation.artifact,
        }
    elif args.operation_name == "finalize":
        artifact = store.finalize(args.operation)
        value = artifact.manifest
    elif args.operation_name == "inspect":
        value = store.resolve(args.artifact).manifest
    else:
        value = store.binding(args.artifact)
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
