import argparse
import json
import sys
import subprocess
from pathlib import Path

from . import InstallError
from .state_contract import StateError, decode, validate
from .state_inspect import inspect_report
from .state_probe import probe_live
from .state_provision import stage_overlay, prepare_live
from .state_initialize import authorize_live, initialize_live
from .state_admission import serve_stdin, serve_listener
from . import beacon_profile
from .artifact import stage
from .filesystem import build_root_fixture
from .image import inspect, install
from .layout import plan
from .manifest import MIB, parse
from .preflight import assess, collect


def main(argv=None):
    parser = argparse.ArgumentParser(prog="host-install")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "preflight", "assemble-fixture"):
        cmd = sub.add_parser(name)
        cmd.add_argument("manifest", type=Path)
        cmd.add_argument("--disk-mib", required=True, type=int)
        if name == "preflight":
            cmd.add_argument("--target", required=True)
            cmd.add_argument("--identity", required=True)
        if name == "assemble-fixture":
            cmd.add_argument("--artifacts", type=Path, required=True)
            cmd.add_argument("--operation", type=Path, required=True)
    cmd = sub.add_parser("inspect")
    cmd.add_argument("operation", type=Path)
    cmd = sub.add_parser("stage-artifact")
    cmd.add_argument("directory", type=Path)
    cmd.add_argument("--expected-id", required=True)
    cmd.add_argument("--operation", type=Path, required=True)
    cmd = sub.add_parser("build-root-fixture")
    cmd.add_argument("staging", type=Path)
    cmd.add_argument("--operation", type=Path, required=True)
    cmd.add_argument("--mib", type=int, required=True)
    cmd.add_argument("--filesystem-uuid", required=True)
    cmd = sub.add_parser("state-validate", help="validate an offline synthetic record bundle")
    cmd.add_argument("bundle", type=Path)
    sub.add_parser("state-inspect", help="read-only inspection of canonical live STATE")
    sub.add_parser("state-probe", help="explicit STATE write probe as UID/GID 970")
    cmd = sub.add_parser("state-stage", help="publish a new offline configuration overlay")
    cmd.add_argument("bundle", type=Path)
    cmd.add_argument("--output", type=Path, required=True)
    cmd.add_argument("--previous-bundle", type=Path)
    cmd.add_argument("--ca-directory", type=Path)
    cmd = sub.add_parser("state-prepare", help="provision directories only on verified live STATE")
    cmd.add_argument("--initialize-volume", help="explicit fresh volume UUID; never generates a key")
    cmd = sub.add_parser("state-authorize", help="explicit root-owned identity initialization authorization")
    cmd.add_argument("--initialization-id", required=True)
    sub.add_parser("state-initialize", help="consume an existing installer authorization using UID 970")
    sub.add_parser("state-admission-serve", help="serve one privileged observation on a systemd accepted socket")
    cmd = sub.add_parser("beacon-prepare", help="explicit supervisor provisioning; never run at boot")
    cmd.add_argument("--state-volume-id", required=True)
    cmd = sub.add_parser("beacon-stage", help="stage reviewed managed-beacon systemd profile offline")
    cmd.add_argument("--discover-source", type=Path, required=True)
    cmd.add_argument("--producer-source", type=Path, help="optional checkout used only to verify packaged host-install templates")
    cmd.add_argument("--output", type=Path, required=True)
    cmd.add_argument("--executable-directory", default="/usr/bin")
    sub.add_parser("state-admission-listen", help="serve the systemd listener until ordered shutdown")
    args = parser.parse_args(argv)
    try:
        if args.command == "state-admission-listen":
            serve_listener()
            return 0
        elif args.command == "beacon-prepare":
            result = beacon_profile.prepare_live(args.state_volume_id)
        elif args.command == "beacon-stage":
            result = beacon_profile.stage(args.discover_source, args.producer_source, args.output, args.executable_directory)
        elif args.command == "state-admission-serve":
            serve_stdin()
            return 0  # stdout is the protocol socket; never append a CLI envelope.
        elif args.command == "state-stage":
            with args.bundle.open("rb") as stream:
                bundle = validate(decode(stream.read(65537)))
            previous = None
            if args.previous_bundle:
                with args.previous_bundle.open("rb") as stream:
                    previous = validate(decode(stream.read(65537)))
            ca = {}
            if args.ca_directory:
                for reg in bundle["bootstrap"]["registries"]:
                    if reg["ca"] is not None:
                        with (args.ca_directory / (reg["registry_id"] + ".pem")).open("rb") as stream:
                            ca[reg["registry_id"]] = stream.read(65537)
            result = stage_overlay(bundle, args.output, previous, ca)
        elif args.command == "state-prepare":
            result = prepare_live(args.initialize_volume)
        elif args.command == "state-authorize":
            result = authorize_live(args.initialization_id)
        elif args.command == "state-initialize":
            result = initialize_live()
        elif args.command == "state-validate":
            with args.bundle.open("rb") as stream:
                validate(decode(stream.read(65537)))
            result = {"status": "offline-records-valid", "control_authorized": False}
        elif args.command == "state-inspect":
            result = inspect_report()
        elif args.command == "state-probe":
            result = probe_live()
        elif args.command == "inspect":
            result = inspect(args.operation)
        elif args.command == "stage-artifact":
            result = stage(args.directory, args.expected_id, args.operation)
        elif args.command == "build-root-fixture":
            result = build_root_fixture(args.staging, args.operation, args.mib, args.filesystem_uuid)
        else:
            m = parse(args.manifest.read_bytes())
            p = plan(m, args.disk_mib * MIB)
            if args.command == "plan":
                result = p
            elif args.command == "preflight":
                result = assess(collect(), args.target, args.identity, p["disk_bytes"])
            else:
                result = install(m, args.artifacts, args.operation, p["disk_bytes"])
        print(json.dumps({"ok": True, "result": result}, indent=2))
        return 0
    except StateError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}), file=sys.stderr)
        return 2
    except (InstallError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
