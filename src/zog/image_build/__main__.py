import argparse
import json
from pathlib import Path
from . import ImageBuild, read_selection
from .metadata import literal


def main():
    parser = argparse.ArgumentParser(description="Build source-only Zog images")
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--controller-config", type=Path)
    parser.add_argument("--source-mirror-config", type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    host = sub.add_parser("import-bootstrap")
    host.add_argument("root", type=Path)
    host.add_argument("provenance", type=Path)
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("host_generation", type=Path)
    bootstrap.add_argument("stages", type=Path)
    build = sub.add_parser("build")
    build.add_argument("toolchain_generation", type=Path)
    build.add_argument("targets", nargs="+")
    check = sub.add_parser("verify-seed")
    check.add_argument("host_generation", type=Path)
    check.add_argument("targets", nargs="+")
    for name in ("resume", "inspect", "release"):
        command = sub.add_parser(name)
        command.add_argument("pipeline_id")
    args = parser.parse_args()
    runner = None
    if args.operation not in ("import-bootstrap", "inspect"):
        if args.controller_config is None:
            parser.error("--controller-config is required for execution and release")
        from .configuration import configured_runner
        runner = configured_runner(args.controller_config, args.state_dir)
    source_mirror = None
    if args.source_mirror_config is not None:
        from .archive_mirror import configured_source_mirror
        source_mirror = configured_source_mirror(args.source_mirror_config)
    builder = ImageBuild(
        package_dir=args.package_dir,
        state_dir=args.state_dir,
        runner=runner,
        source_mirror=source_mirror,
    )
    if args.operation == "inspect":
        print(json.dumps(builder.inspect_pipeline(args.pipeline_id), indent=2))
        return
    if args.operation == "release":
        print(json.dumps(builder.release_pipeline(args.pipeline_id), indent=2))
        return
    if args.operation == "import-bootstrap":
        result = builder.import_bootstrap(
            args.root, json.loads(args.provenance.read_text())
        )
    elif args.operation == "bootstrap":
        result = builder.bootstrap(
            read_selection(args.host_generation), literal(args.stages)
        )
    elif args.operation == "verify-seed":
        result = builder.verify_seed(args.targets, host_bootstrap=read_selection(args.host_generation))
    elif args.operation == "resume":
        result = builder.resume(args.pipeline_id)
    else:
        result = builder.ensure(
            args.targets, toolchain=read_selection(args.toolchain_generation)
        )
    print(
        json.dumps(
            {
                "generation": result.generation,
                "root": str(result.root.resolve()),
                "reused": result.reused,
            }
        )
    )


if __name__ == "__main__":
    main()
