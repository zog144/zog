"""Immutable symlink-composed application software views.

A view is a deterministic composition of already-published ``applications-v1``
artifacts. The view itself contains only directories and symlinks. At runtime,
box-control mounts each referenced artifact read-only below ``/applications/.store``
and the view read-only below ``/applications/<application>``.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .application_software import (
    ApplicationSoftwareStore,
    MOUNT_CONTRACT,
    compatibility,
)
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
VIEW_KIND = "application-software-view"
VIEW_CONTRACT = "application-software-view-v1"
CONSUMER_CONTRACT = "application-software-consumer-v1"
_RUNTIME_ROOT = PurePosixPath("/applications")
_RUNTIME_STORE = _RUNTIME_ROOT / ".store"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_OPERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROFILES = {"application", "everything"}
_VISIBILITY = {
    "executables": ["bin"],
    "libraries": ["lib", "lib64"],
    "resources": ["share"],
    "helpers": ["libexec"],
}


@dataclass(frozen=True)
class ApplicationSoftwareView:
    view: str
    root: Path
    manifest: dict
    reused: bool = False


def _copy(value):
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as error:
        raise ImageBuildError(
            "application software view metadata must be JSON data"
        ) from error


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _identity(manifest):
    payload = {
        key: value for key, value in manifest.items() if key != "view"
    }
    return "sha256:" + hashlib.sha256(
        _canonical(payload).encode("utf-8")
    ).hexdigest()


def _object_hex(value, label):
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or not _SHA256.fullmatch(value[7:])
    ):
        raise ImageBuildError(
            "invalid application software " + label + " identity"
        )
    return value[7:]


def _name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ImageBuildError("invalid application software view " + label)
    return value


def _operation(value):
    if not isinstance(value, str) or not _OPERATION.fullmatch(value):
        raise ImageBuildError(
            "invalid application software view operation identity"
        )
    return value


def _relative(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or "\x00" in value
    ):
        raise ImageBuildError("invalid application software view path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ImageBuildError("invalid application software view path")
    return path.as_posix()


def _runtime_target(application, artifact, path):
    application = _name(application, "application")
    artifact_hex = _object_hex(artifact, "artifact")
    relative = _relative(path)
    destination = _RUNTIME_ROOT / application / relative
    source = _RUNTIME_STORE / artifact_hex / relative
    target = posixpath.relpath(
        source.as_posix(), destination.parent.as_posix()
    )
    normalized = PurePosixPath(
        posixpath.normpath((destination.parent / target).as_posix())
    )
    prefix = _RUNTIME_STORE / artifact_hex
    if normalized != prefix and prefix not in normalized.parents:
        raise ImageBuildError(
            "application software view target escapes runtime store"
        )
    return target


def _manifest_inputs(store, application, profile, artifacts):
    application = _name(application, "application")
    if profile not in _PROFILES:
        raise ImageBuildError(
            "unsupported application software view profile"
        )
    if not isinstance(artifacts, (list, tuple)) or not artifacts:
        raise ImageBuildError(
            "application software view requires artifacts"
        )
    artifact_ids = sorted(set(artifacts))
    if len(artifact_ids) != len(artifacts):
        raise ImageBuildError(
            "duplicate application software view artifact"
        )
    resolved = []
    for artifact_id in artifact_ids:
        _object_hex(artifact_id, "artifact")
        artifact = store.resolve(artifact_id)
        if artifact.manifest["application"] != application:
            raise ImageBuildError(
                "application software view artifact belongs to another application"
            )
        resolved.append(artifact)
    return application, profile, artifact_ids, resolved


def _composition(application, resolved):
    owners = {}
    directories = {}
    leaves = []
    for artifact in resolved:
        for record in artifact.manifest["outputs"]:
            path = _relative(record["path"])
            previous = owners.get(path)
            if record["kind"] == "directory":
                if previous is not None and previous["kind"] != "directory":
                    raise ImageBuildError(
                        "application software view path collision: " + path
                    )
                mode = record["mode"]
                if path in directories and directories[path] != mode:
                    raise ImageBuildError(
                        "application software view directory mode collision: "
                        + path
                    )
                directories[path] = mode
                owners[path] = {"kind": "directory", "artifact": None}
                continue
            if previous is not None:
                raise ImageBuildError(
                    "application software view path collision: " + path
                )
            target = _runtime_target(
                application, artifact.artifact, path
            )
            owners[path] = {
                "kind": "symlink",
                "artifact": artifact.artifact,
                "artifact_path": path,
                "target": target,
            }
            leaves.append(
                {
                    "path": path,
                    "kind": "symlink",
                    "mode": 0o777,
                    "artifact": artifact.artifact,
                    "artifact_path": path,
                    "target": target,
                }
            )

    leaf_paths = {entry["path"] for entry in leaves}
    for path in owners:
        parent = PurePosixPath(path).parent
        while parent != PurePosixPath("."):
            if parent.as_posix() in leaf_paths:
                raise ImageBuildError(
                    "application software view parent path collision: "
                    + path
                )
            parent = parent.parent

    directories = [
        {
            "path": path,
            "kind": "directory",
            "mode": directories[path],
        }
        for path in sorted(directories)
    ]
    composition = sorted(
        directories + leaves, key=lambda value: value["path"]
    )
    outputs = [
        {
            "path": item["path"],
            "mode": item["mode"],
            "kind": item["kind"],
            **(
                {"target": item["target"]}
                if item["kind"] == "symlink"
                else {}
            ),
        }
        for item in composition
    ]
    return composition, outputs


def _manifest(store, application, profile, artifacts):
    application, profile, artifact_ids, resolved = _manifest_inputs(
        store, application, profile, artifacts
    )
    composition, outputs = _composition(application, resolved)
    manifest = {
        "schema": SCHEMA,
        "kind": VIEW_KIND,
        "contract": VIEW_CONTRACT,
        "mount_contract": MOUNT_CONTRACT,
        "view": "",
        "application": application,
        "profile": profile,
        "artifacts": artifact_ids,
        "visibility": _copy(_VISIBILITY),
        "composition": composition,
        "outputs": outputs,
    }
    manifest["view"] = _identity(manifest)
    return manifest


def _validate_manifest(store, manifest):
    required = {
        "schema",
        "kind",
        "contract",
        "mount_contract",
        "view",
        "application",
        "profile",
        "artifacts",
        "visibility",
        "composition",
        "outputs",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or manifest.get("schema") != SCHEMA
        or manifest.get("kind") != VIEW_KIND
        or manifest.get("contract") != VIEW_CONTRACT
        or manifest.get("mount_contract") != MOUNT_CONTRACT
        or manifest.get("visibility") != _VISIBILITY
    ):
        raise ImageBuildError(
            "unsupported application software view manifest"
        )
    _object_hex(manifest.get("view"), "view")
    if _identity(manifest) != manifest["view"]:
        raise ImageBuildError(
            "application software view identity changed"
        )
    expected = _manifest(
        store,
        manifest["application"],
        manifest["profile"],
        manifest["artifacts"],
    )
    if expected != manifest:
        raise ImageBuildError(
            "application software view composition changed"
        )
    return manifest


def read_view(store, directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ImageBuildError(
            "invalid application software view directory"
        )
    view = "sha256:" + directory.name
    _object_hex(view, "view")
    manifest_path = directory / "manifest.json"
    root = directory / "root"
    if (
        manifest_path.is_symlink()
        or root.is_symlink()
        or not root.is_dir()
    ):
        raise ImageBuildError(
            "invalid application software view layout"
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError, TypeError) as error:
        raise ImageBuildError(
            "invalid application software view manifest"
        ) from error
    if manifest.get("view") != view:
        raise ImageBuildError(
            "application software view directory identity changed"
        )
    _validate_manifest(store, manifest)
    if inventory(root) != manifest["outputs"]:
        raise ImageBuildError(
            "application software view links changed"
        )
    return ApplicationSoftwareView(
        view, root, manifest, True
    )


def _publish_candidate(candidate, target):
    os.replace(candidate, target)
    sync_directory(target.parent)


class ApplicationSoftwareViewStore:
    """Durable immutable composition above ApplicationSoftwareStore."""

    def __init__(self, state_dir):
        self.artifacts = ApplicationSoftwareStore(state_dir)
        self.state = self.artifacts.state
        self.root = self.artifacts.root
        for name in (
            "view-operations",
            "view-candidates",
            "views",
        ):
            ensure_directory(self.root / name)

    def _operation_path(self, operation):
        return (
            self.root
            / "view-operations"
            / _operation(operation)
        )

    def _view_path(self, view):
        return (
            self.root
            / "views"
            / _object_hex(view, "view")
        )

    def _intent(
        self, operation, application, profile, artifacts
    ):
        operation = _operation(operation)
        application = _name(application, "application")
        if profile not in _PROFILES:
            raise ImageBuildError(
                "unsupported application software view profile"
            )
        if (
            not isinstance(artifacts, (list, tuple))
            or not artifacts
        ):
            raise ImageBuildError(
                "application software view requires artifacts"
            )
        artifact_ids = sorted(set(artifacts))
        if len(artifact_ids) != len(artifacts):
            raise ImageBuildError(
                "duplicate application software view artifact"
            )
        for artifact in artifact_ids:
            _object_hex(artifact, "artifact")
        return {
            "schema": SCHEMA,
            "operation": operation,
            "application": application,
            "profile": profile,
            "artifacts": artifact_ids,
        }

    def _frozen(self, path, intent):
        frozen_path = path / "frozen.json"
        if frozen_path.exists():
            try:
                frozen = json.loads(
                    frozen_path.read_text()
                )
            except (
                OSError,
                ValueError,
                TypeError,
            ) as error:
                raise ImageBuildError(
                    "invalid frozen application software view"
                ) from error
            if (
                not isinstance(frozen, dict)
                or set(frozen) != {"schema", "manifest"}
                or frozen.get("schema") != SCHEMA
            ):
                raise ImageBuildError(
                    "unsupported frozen application software view"
                )
            _validate_manifest(
                self.artifacts, frozen["manifest"]
            )
            if (
                frozen["manifest"]["application"]
                != intent["application"]
                or frozen["manifest"]["profile"]
                != intent["profile"]
                or frozen["manifest"]["artifacts"]
                != intent["artifacts"]
            ):
                raise ImageBuildError(
                    "frozen application software view differs from intent"
                )
            return frozen

        manifest = _manifest(
            self.artifacts,
            intent["application"],
            intent["profile"],
            intent["artifacts"],
        )
        frozen = {"schema": SCHEMA, "manifest": manifest}
        write_json(frozen_path, frozen)
        return frozen

    def _compose_candidate(self, operation, manifest):
        candidate = (
            self.root
            / "view-candidates"
            / operation
        )
        if candidate.is_symlink():
            raise ImageBuildError(
                "application software view candidate is a symlink"
            )
        if candidate.exists():
            try:
                saved = json.loads(
                    (candidate / "manifest.json").read_text()
                )
                root = candidate / "root"
                valid = (
                    saved == manifest
                    and not root.is_symlink()
                    and root.is_dir()
                    and inventory(root)
                    == manifest["outputs"]
                )
            except (
                OSError,
                ValueError,
                TypeError,
                ImageBuildError,
            ):
                valid = False
            if valid:
                return candidate
            discard_staging(candidate)

        ensure_directory(candidate)
        root = candidate / "root"
        root.mkdir()
        directories = [
            item
            for item in manifest["composition"]
            if item["kind"] == "directory"
        ]
        leaves = [
            item
            for item in manifest["composition"]
            if item["kind"] == "symlink"
        ]
        for item in directories:
            (root / item["path"]).mkdir(
                parents=True, exist_ok=True
            )
        for item in leaves:
            target = root / item["path"]
            target.parent.mkdir(
                parents=True, exist_ok=True
            )
            target.symlink_to(item["target"])
        for item in sorted(
            directories,
            key=lambda value: len(
                PurePosixPath(
                    value["path"]
                ).parts
            ),
            reverse=True,
        ):
            (root / item["path"]).chmod(item["mode"])
        if inventory(root) != manifest["outputs"]:
            raise ImageBuildError(
                "application software view candidate differs from frozen outputs"
            )
        write_json(
            candidate / "manifest.json", manifest
        )
        sync_tree(candidate)
        return candidate

    def publish(
        self,
        operation,
        *,
        application,
        artifacts,
        profile="application",
    ):
        intent = self._intent(
            operation, application, profile, artifacts
        )
        with self.artifacts.locked():
            path = self._operation_path(operation)
            ensure_directory(path)
            intent_path = path / "intent.json"
            if intent_path.exists():
                try:
                    existing = json.loads(
                        intent_path.read_text()
                    )
                except (
                    OSError,
                    ValueError,
                    TypeError,
                ) as error:
                    raise ImageBuildError(
                        "invalid retained application software view intent"
                    ) from error
                if existing != intent:
                    raise ImageBuildError(
                        "retained application software view operation changed"
                    )
            else:
                write_json(intent_path, intent)

            result_path = path / "result.json"
            if result_path.exists():
                try:
                    result = json.loads(
                        result_path.read_text()
                    )
                    value = self.resolve(
                        result["view"]
                    )
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                ) as error:
                    raise ImageBuildError(
                        "invalid retained application software view result"
                    ) from error
                return ApplicationSoftwareView(
                    value.view,
                    value.root,
                    value.manifest,
                    True,
                )

            frozen = self._frozen(path, intent)
            manifest = frozen["manifest"]
            view_id = manifest["view"]
            target = self._view_path(view_id)
            reused = target.exists()
            if reused:
                existing = read_view(
                    self.artifacts, target
                )
                if existing.manifest != manifest:
                    raise ImageBuildError(
                        "application software view identity collision"
                    )
                candidate = (
                    self.root
                    / "view-candidates"
                    / operation
                )
                if candidate.exists():
                    discard_staging(candidate)
            else:
                candidate = self._compose_candidate(
                    operation, manifest
                )
                if target.exists():
                    raise ImageBuildError(
                        "application software view appeared during publication"
                    )
                _publish_candidate(
                    candidate, target
                )
                existing = read_view(
                    self.artifacts, target
                )
                if existing.manifest != manifest:
                    raise ImageBuildError(
                        "published application software view differs"
                    )
            write_json(
                result_path,
                {
                    "schema": SCHEMA,
                    "operation": operation,
                    "view": view_id,
                },
            )
            value = self.resolve(view_id)
            return ApplicationSoftwareView(
                value.view,
                value.root,
                value.manifest,
                reused,
            )

    def resolve(self, view):
        return read_view(
            self.artifacts, self._view_path(view)
        )

    def consumer_manifest(
        self, view, rootfs_compatibility
    ):
        """Return the verified box-control mount contract."""
        value = self.resolve(view)
        rootfs_compatibility = compatibility(rootfs_compatibility)
        objects = []
        for artifact_id in value.manifest["artifacts"]:
            artifact = (
                self.artifacts.require_compatible(
                    artifact_id,
                    rootfs_compatibility,
                )
            )
            artifact_hex = _object_hex(
                artifact_id, "artifact"
            )
            objects.append(
                {
                    "artifact": artifact_id,
                    "root": str(
                        artifact.root.resolve()
                    ),
                    "mount_point": (
                        _RUNTIME_STORE / artifact_hex
                    ).as_posix(),
                    "manifest": str(
                        (
                            artifact.root.parent
                            / "manifest.json"
                        ).resolve()
                    ),
                    "compatibility": artifact.manifest[
                        "compatibility"
                    ],
                }
            )
        result = {
            "schema": SCHEMA,
            "contract": CONSUMER_CONTRACT,
            "mount_contract": MOUNT_CONTRACT,
            "view": value.view,
            "application": value.manifest[
                "application"
            ],
            "profile": value.manifest["profile"],
            "root": str(value.root.resolve()),
            "manifest": str(
                (value.root.parent / "manifest.json").resolve()
            ),
            "mount_point": (
                _RUNTIME_ROOT
                / value.manifest["application"]
            ).as_posix(),
            "objects": objects,
            "rootfs_compatibility": rootfs_compatibility,
            "visibility": _copy(
                value.manifest["visibility"]
            ),
            "reclamation_protection": {
                "view": value.view,
                "artifacts": list(
                    value.manifest["artifacts"]
                ),
            },
        }
        result["binding_digest"] = "sha256:" + hashlib.sha256(
            _canonical(result).encode("utf-8")
        ).hexdigest()
        return result

    def referenced_artifacts(self, view):
        """Return exact artifacts retained by a view."""
        return tuple(
            self.resolve(view).manifest["artifacts"]
        )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument(
        "--state-dir", type=Path, required=True
    )
    sub = parser.add_subparsers(
        dest="operation_name", required=True
    )

    publish = sub.add_parser("publish")
    publish.add_argument("operation")
    publish.add_argument("declaration", type=Path)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("view")

    binding = sub.add_parser("binding")
    binding.add_argument("view")
    binding.add_argument(
        "rootfs_compatibility", type=Path
    )

    args = parser.parse_args()
    store = ApplicationSoftwareViewStore(
        args.state_dir
    )
    if args.operation_name == "publish":
        try:
            declaration = json.loads(
                args.declaration.read_text()
            )
        except (
            OSError,
            ValueError,
            TypeError,
        ) as error:
            raise SystemExit(
                "invalid application software view declaration: "
                + str(error)
            )
        value = store.publish(
            args.operation,
            application=declaration["application"],
            artifacts=declaration["artifacts"],
            profile=declaration.get(
                "profile", "application"
            ),
        ).manifest
    elif args.operation_name == "inspect":
        value = store.resolve(args.view).manifest
    else:
        try:
            rootfs = json.loads(
                args.rootfs_compatibility.read_text()
            )
        except (
            OSError,
            ValueError,
            TypeError,
        ) as error:
            raise SystemExit(
                "invalid rootfs compatibility descriptor: "
                + str(error)
            )
        value = store.consumer_manifest(
            args.view, rootfs
        )
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
