"""DNF4 evidence collector, intended for Amazon Linux 2023's system Python.

DNF solves binary installation requirements. Source RPM build requirements are
recorded separately for review; this is not automatic Zog recipe translation.
"""

import argparse
import json
import subprocess
from pathlib import Path
from ..errors import ImageBuildError
from ..filesystem import digest, write_json
from ..metadata import names
from .source_packaging import extract


def discover(requested):
    names(requested)
    try:
        import dnf
    except ImportError as error:
        raise ImageBuildError(
            "developer discovery requires DNF4 Python bindings on the host"
        ) from error
    with dnf.Base() as base:
        # Resolve independently of what happens to be installed on the developer host.
        base.read_all_repos()
        base.fill_sack(load_system_repo=False)
        for name in requested:
            base.install(name)
        base.resolve()
        selected = list(base.transaction.install_set)
        records = []
        for package in sorted(selected, key=str):
            requirements = []
            for requirement in package.requires:
                providers = {
                    str(p) for p in base.sack.query().filter(provides=requirement)
                }
                requirements.append(
                    {
                        "requirement": str(requirement),
                        "selected_providers": sorted(
                            str(p) for p in selected if str(p) in providers
                        ),
                    }
                )
            records.append(
                {
                    "nevra": str(package),
                    "name": package.name,
                    "source_rpm": package.sourcerpm,
                    "repository": package.reponame,
                    "url": package.remote_location(),
                    "architecture": package.arch,
                    "requires": requirements,
                }
            )
        return {
            "schema": 1,
            "status": "developer-evidence-only",
            "requested": list(requested),
            "packages": records,
            "repositories": [
                {
                    "id": r.id,
                    "baseurl": list(r.baseurl),
                    "metalink": r.metalink,
                    "mirrorlist": r.mirrorlist,
                }
                for r in base.repos.iter_enabled()
            ],
        }


def collect_sources(evidence, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    source_names = {}
    for package in evidence["packages"]:
        source_names.setdefault(package["source_rpm"], package["nevra"])
    for source_name, binary in sorted(source_names.items()):
        if not source_name or Path(source_name).name != source_name:
            raise ImageBuildError("repository did not supply a valid source RPM name")
        subprocess.run(
            ["dnf", "download", "--source", "--destdir", str(destination), binary],
            check=True,
        )
        source = destination / source_name
        if not source.is_file():
            raise ImageBuildError(f"exact source RPM was not retrieved: {source_name}")
        # Signature verification is explicit; unavailable keys block evidence acceptance.
        subprocess.run(["rpmkeys", "--checksig", str(source)], check=True)

        def query(*arguments):
            return subprocess.check_output(
                ["rpm", "-qp", *arguments, str(source)], text=True
            ).splitlines()

        results.append(
            {
                "source_rpm": source_name,
                "sha256": digest(source),
                "build_requires": query("--requires"),
                "payload_files": query("--list"),
                "extracted_files": extract(
                    source, destination / (source_name + ".packaging")
                ),
                "note": "Full source RPM retained, including spec and patches; hooks/macros require review.",
            }
        )
    return {**evidence, "source_packaging": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="+")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--sources", action="store_true")
    args = parser.parse_args()
    evidence = discover(args.packages)
    if args.sources:
        evidence = collect_sources(evidence, args.destination / "source-rpms")
    write_json(args.destination / "evidence.json", evidence)


if __name__ == "__main__":
    main()
