"""CLI for integrate-observe World/Comparison factual inspection."""
import argparse
import json
import sys

from .observer import IntegrationObserver, ObservationError, SCHEMA_VERSION


def _trace(args):
    try:
        from zog.build_trace import BuildTrace, TraceError
    except ImportError as exc:
        raise ObservationError(
            "dependency-unavailable",
            "Install build-trace 0.12.x before using the CLI.",
        ) from exc
    try:
        return BuildTrace(
            args.project_root,
            host_id=args.host_id,
            record_store=args.record_store,
            record_project_id=args.record_project_id,
        )
    except TraceError as exc:
        raise ObservationError(getattr(exc, "code", "build-trace-error"), str(exc)) from exc


def _parser():
    parser = argparse.ArgumentParser(prog="integrate-observe")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--record-store", required=True)
    parser.add_argument("--record-project-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    world = sub.add_parser("world", help="Inspect one caller-selected observation world")
    world.add_argument("snapshot")

    compare = sub.add_parser("compare", help="Compare caller-selected baseline and candidate worlds")
    compare.add_argument("baseline_snapshot")
    compare.add_argument("candidate_snapshot")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        observer = IntegrationObserver(_trace(args))
        if args.command == "world":
            result = observer.world(args.snapshot)
        else:
            result = observer.compare(args.baseline_snapshot, args.candidate_snapshot)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except ObservationError as exc:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "kind": "error",
            "error": {"code": exc.code, "message": exc.message},
        }, sort_keys=True, separators=(",", ":")))
        return 2
    except Exception as exc:
        # BuildTrace TraceError is deliberately not imported into observer.py. Preserve
        # a bounded public failure shape rather than exposing arbitrary exception text.
        code = getattr(exc, "code", None)
        if isinstance(code, str):
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "kind": "error",
                "error": {"code": code, "message": "build-trace query failed"},
            }, sort_keys=True, separators=(",", ":")))
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
