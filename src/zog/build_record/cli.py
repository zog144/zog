"""JSON CLI. Exit 2: invalid/unavailable; exit 3: incomplete/unverified requested check."""
import argparse
import json
from pathlib import Path

from . import RecordError, Store, audit_generation, canonical, compare, inspect, loads, record_id, verify_artifacts
from .model import MAX_BUNDLE_BYTES


def read(path):
    with Path(path).open("rb") as stream:
        return loads(stream.read(MAX_BUNDLE_BYTES + 1), MAX_BUNDLE_BYTES)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="build-record")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("file")
        if name == "verify":
            sub.add_argument("--artifacts", required=True, help="JSON digest-to-local-path mapping")
    sub = commands.add_parser("put")
    sub.add_argument("store")
    sub.add_argument("file")
    sub = commands.add_parser("export")
    sub.add_argument("store")
    sub.add_argument("roots", nargs="+")
    sub = commands.add_parser("compare")
    sub.add_argument("before")
    sub.add_argument("after")
    sub = commands.add_parser("audit-generation")
    sub.add_argument("file")
    sub.add_argument("--expected", required=True, help="Independent owner root, generation identity and package set")
    sub.add_argument("--artifacts", help="Optional JSON digest-to-local-path mapping")
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.command == "validate":
            result = {"record_id": record_id(read(args.file)), "valid": True}
        elif args.command == "put":
            result = {"record_id": Store(args.store).put(read(args.file))}
        elif args.command == "export":
            result = Store(args.store).bundle(args.roots)
        elif args.command == "compare":
            result = compare(read(args.before), read(args.after))
        elif args.command == "inspect":
            result = inspect(read(args.file))
            code = 0 if result["complete"] else 3
        elif args.command == "audit-generation":
            paths = read(args.artifacts) if args.artifacts else None
            if paths is not None and (type(paths) is not dict or any(type(x) is not str for x in paths.values())):
                raise RecordError("artifact mapping must contain local path strings")
            result = audit_generation(read(args.file), read(args.expected), paths=paths)
            code = 0 if result['passed'] else 3
        else:
            paths = read(args.artifacts)
            if type(paths) is not dict or any(type(x) is not str for x in paths.values()):
                raise RecordError("artifact mapping must contain local path strings")
            result = verify_artifacts(read(args.file), paths)
            code = 0 if result["complete"] and all(x["status"] == "verified"
                         for x in result["artifact_verification"]) else 3
    except (RecordError, OSError) as exc:
        result = {"error": {"code": "invalid-or-unavailable", "message":
                  str(exc) if isinstance(exc, RecordError) else "local file operation failed"}}
        code = 2
    print(canonical(result).decode("ascii"))
    return code
