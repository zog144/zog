#!/usr/bin/env python3
"""Reject stale pre-zog Python namespaces and obsolete nested repository paths."""
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
PACKAGE = SOURCE / "zog" / "station_access"
TESTS = ROOT / "tests"

errors = []

def fail(message):
    errors.append(message)

if not PACKAGE.is_dir():
    fail("missing src/zog/station_access")
if (SOURCE / "zog" / "__init__.py").exists():
    fail("component must not own src/zog/__init__.py")
if not (PACKAGE / "__init__.py").is_file():
    fail("component package __init__.py is missing")
if not (PACKAGE / "cli.py").is_file():
    fail("stable CLI module zog.station_access.cli is missing")
if (ROOT / "station-access").exists():
    fail("obsolete inner station-access project directory still exists")

runtime_tests = [
    path for path in PACKAGE.rglob("*.py")
    if path.name.startswith("test_") or "tests" in path.parts
]
if runtime_tests:
    fail("developer tests leaked into runtime package: " + ", ".join(str(p.relative_to(ROOT)) for p in runtime_tests))

developer_docs = list(PACKAGE.rglob("*.md"))
if developer_docs:
    fail("developer documentation leaked into runtime package: " + ", ".join(str(p.relative_to(ROOT)) for p in developer_docs))

for old in ("station_access", "host_registry", "archive_inventory", "station_access_project"):
    legacy = ROOT / "backend" / old
    if legacy.exists():
        fail(f"obsolete runtime package still exists: {legacy.relative_to(ROOT)}")

pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
if pyproject["project"].get("scripts", {}).get("station-access") != "zog.station_access.cli:main":
    fail("station-access script must resolve to zog.station_access.cli:main")
find = pyproject.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
if find.get("where") != ["src"] or find.get("include") != ["zog.station_access*"]:
    fail("setuptools package discovery must select only zog.station_access from src")

fixture = PACKAGE / "host_registry" / "fixtures" / "managed-state.json"
if not fixture.is_file():
    fail("managed-state runtime fixture is missing from package tree")
if not (ROOT / "frontend" / "toolchain.json").is_file():
    fail("frontend build source must remain at frontend/toolchain.json")
if not (ROOT / "integration" / "application.py").is_file():
    fail("image-build integration declaration must remain at integration/application.py")

old_modules = (
    "station_access", "station_access_project", "host_registry", "archive_inventory",
    "box_control", "host_identify", "archive_mirror", "network_register",
    "host_deploy", "host_discover", "host_install", "image_build",
)
module_alt = "|".join(map(re.escape, old_modules))
import_pattern = re.compile(rf"(?m)^\s*(?:from|import)\s+(?:{module_alt})(?:\.|\s|$)")
dynamic_pattern = re.compile(rf"(?m)[\"'](?:{module_alt})\.[a-z_]")
legacy_patterns = [
    re.compile(r"station_access_project\.(?:settings|urls|wsgi|asgi)"),
    re.compile(r"zog\.zog\."),
    re.compile(r"/opt/station-access/backend"),
    re.compile(r"station-access/backend"),
    re.compile(r"station-access-first-use"),
]
nested_source_patterns = [
    re.compile(r"(?<![/A-Za-z0-9_.-])station-access/(?:src|tests|frontend|integration|docs)(?:/|\b)"),
    re.compile(r"(?<![/A-Za-z0-9_.-])station-access/(?:pyproject\.toml|manage\.py|serve\.py|requirements-tested\.txt)\b"),
]

scan_roots = [ROOT / "src", ROOT / "tests", ROOT / "frontend", ROOT / "tools", ROOT / "deployment", ROOT / "integration", ROOT / ".github"]
suffixes = {".py", ".toml", ".service", ".timer", ".sh", ".yml", ".yaml", ".mjs", ".ts", ".tsx"}
for base in scan_roots:
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if path.resolve() == Path(__file__).resolve():
            continue
        if not path.is_file() or path.suffix not in suffixes:
            continue
        text = path.read_text(errors="replace")
        relative = path.relative_to(ROOT)
        patterns = [import_pattern, *legacy_patterns, *nested_source_patterns]
        if "migrations" not in path.parts:
            patterns.append(dynamic_pattern)
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                fail(f"stale namespace/layout reference {relative}:{line}: {match.group(0)!r}")

for path in TESTS.rglob("*.py"):
    text = path.read_text(errors="replace")
    if re.search(r"(?m)^\s*(?:from|import)\s+(?:station_access|host_registry|archive_inventory)(?:\.|\s|$)", text):
        fail(f"test can import obsolete local package layout: {path.relative_to(ROOT)}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)

print("station-access namespace/layout contract: OK")
