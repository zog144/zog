"""Reviewed definitions are Python literals, never imported executable modules."""

import ast
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
from .errors import ImageBuildError


def identity(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def literal(path):
    try:
        return ast.literal_eval(Path(path).read_text())
    except (OSError, ValueError, SyntaxError) as error:
        raise ImageBuildError(f"invalid literal metadata {path}: {error}") from error


def relative(value):
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or ".." in PurePosixPath(value).parts
        or "." == value
    ):
        raise ImageBuildError(f"unsafe relative path: {value!r}")
    return value


def names(values):
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9+_.-]*", v)
        for v in values
    ):
        raise ImageBuildError(f"invalid package names: {values!r}")
    if len(values) != len(set(values)):
        raise ImageBuildError("duplicate package names")
    return tuple(values)


@dataclass(frozen=True)
class Package:
    name: str
    sources: tuple
    build_dependencies: tuple
    runtime_dependencies: tuple
    steps: dict
    environment: dict
    outputs: tuple
    integration: dict
    output_trees: tuple = ()
    licensing: dict | None = None
    test_dependencies: tuple = ()
    recipe_directory: str | None = None
    source_provenance: dict | None = None

    @property
    def fingerprint(self):
        record = asdict(self)
        record.pop("recipe_directory", None)
        if self.source_provenance is None: record.pop("source_provenance")
        if self.licensing is None: record.pop("licensing")
        if not self.test_dependencies: record.pop("test_dependencies")
        return identity(record)


def load_package(directory):
    directory = Path(directory)
    names([directory.name])
    catalogue_path = directory / "package.py"
    if catalogue_path.exists():
        catalogue = literal(catalogue_path)
        if isinstance(catalogue, dict) and catalogue.get("status") == "catalogue-only":
            raise ImageBuildError(
                f"{directory.name}: catalogue-only; author and review stage recipes, "
                "source SHA256 digests and output manifests before building"
            )
    sources = literal(directory / "sources.py")
    dependencies = literal(directory / "dependencies.py")
    build = literal(directory / "build.py")
    outputs = literal(directory / "produce-manifest.py")
    if not isinstance(sources, list) or not sources:
        raise ImageBuildError(
            f"{directory.name}: at least one source input is required"
        )
    destinations = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {
            "url",
            "sha256",
            "destination",
            "archive",
        }:
            raise ImageBuildError("source requires url, sha256, destination, archive")
        if not isinstance(source["url"], str) or not source["url"].startswith(
            ("https://", "file:", "recipe:")
        ):
            raise ImageBuildError("source URL must use https, file or recipe")
        if not isinstance(source["sha256"], str) or not re.fullmatch(
            "[0-9a-f]{64}", source["sha256"]
        ):
            raise ImageBuildError("source requires a SHA256 digest")
        if source["url"].startswith("recipe:"):
            relative(source["url"][7:])
            if source["archive"]:
                raise ImageBuildError("recipe sources must be plain files")
        relative(source["destination"])
        if source["destination"] in destinations:
            raise ImageBuildError("duplicate source destination")
        destinations.add(source["destination"])
        if type(source["archive"]) is not bool:
            raise ImageBuildError("archive must be boolean")
    if (not isinstance(dependencies, dict)
            or not {"build", "runtime"}.issubset(dependencies)
            or set(dependencies) - {"build", "runtime", "test"}):
        raise ImageBuildError("dependencies requires build and runtime lists, with optional test list")
    if not isinstance(build, dict) or set(build) - {
        "prepare",
        "configure",
        "build",
        "test",
        "install",
        "environment",
    }:
        raise ImageBuildError("unknown build metadata field")
    steps = {}
    for phase in ("prepare", "configure", "build", "test", "install"):
        commands = build.get(phase, [])
        if not isinstance(commands, list) or any(
            not isinstance(c, list)
            or not c
            or any(not isinstance(a, str) or "\0" in a for a in c)
            for c in commands
        ):
            raise ImageBuildError(f"{phase}: expected list of argument lists")
        steps[phase] = commands
    if not steps["build"] or not steps["install"]:
        raise ImageBuildError("build and install steps must be explicit")
    environment = build.get("environment", {})
    if not isinstance(environment, dict) or any(
        not isinstance(k, str)
        or not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", k)
        or not isinstance(v, str)
        or "\0" in v
        for k, v in environment.items()
    ):
        raise ImageBuildError("invalid build environment")
    if set(environment) & {
        "DESTDIR",
        "HOME",
        "IMAGE_BUILD_SOURCE",
        "IMAGE_BUILD_OUTPUT",
    }:
        raise ImageBuildError("build environment overrides reserved paths")
    output_trees = ()
    if isinstance(outputs, dict):
        if set(outputs) != {'trees', 'required'}:
            raise ImageBuildError('tree output policy requires trees and required')
        trees = outputs['trees']
        if not isinstance(trees, list) or not trees or len(trees) != len(set(trees)):
            raise ImageBuildError('unique output trees required')
        output_trees = tuple(relative(tree) for tree in trees)
        outputs = outputs['required']
    if (
        not isinstance(outputs, list)
        or not outputs
        or any(not isinstance(p, str) for p in outputs)
        or len(outputs) != len(set(outputs))
    ):
        raise ImageBuildError("produce-manifest requires unique exact output paths")
    for output in outputs:
        relative(output)
    integration_path = directory / "integration.py"
    integration = literal(integration_path) if integration_path.exists() else {}
    if not isinstance(integration, dict):
        raise ImageBuildError("integration metadata must be a mapping")
    license_path = directory / 'license.py'
    if not license_path.exists() and directory.parent.name == 'stages':
        license_path = directory.parent.parent / 'license.py'
    from .licensing import load as load_license
    licensing = load_license(license_path) if license_path.exists() else None
    if licensing and licensing['source']['sha256'] not in {s['sha256'] for s in sources}:
        raise ImageBuildError('license source identity differs from package recipe')
    from .source_provenance import NAME, load as load_source_provenance
    provenance_path = directory / NAME
    source_provenance = load_source_provenance(provenance_path, sources) if provenance_path.exists() or provenance_path.is_symlink() else None
    return Package(
        directory.name,
        tuple(sources),
        names(dependencies["build"]),
        names(dependencies["runtime"]),
        steps,
        environment,
        tuple(sorted(outputs)),
        integration,
        output_trees,
        licensing,
        names(dependencies.get("test", [])),
        str(directory.resolve()),
        source_provenance,
    )


def load_packages(directory):
    return {
        p.name: load_package(p)
        for p in sorted(Path(directory).iterdir())
        if p.is_dir() and not p.name.startswith(".")
    }


def order(packages, targets, *, runtime_only=False):
    result, visiting, visited = [], set(), set()

    def visit(name):
        if name in visiting:
            raise ImageBuildError(
                f"dependency cycle at {name}; bootstrap stages must break cycles explicitly"
            )
        if name in visited:
            return
        if name not in packages:
            raise ImageBuildError(f"missing reviewed package definition: {name}")
        visiting.add(name)
        package = packages[name]
        for dependency in sorted(
            set(
                package.runtime_dependencies
                + (() if runtime_only else package.build_dependencies + package.test_dependencies)
            )
        ):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        result.append(name)

    for target in names(targets):
        visit(target)
    return tuple(result)
