#!/usr/bin/env python3
"""Package the readable reboot fixture without executing it; output stays outside Git."""
import argparse
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    options = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    output = options.output.resolve()
    if output.is_relative_to(repository):
        parser.error('Choose an output path outside the repository')
    if output.suffix != '.zip':
        parser.error('Output must have a .zip suffix')
    fixture = Path(__file__).resolve().parent / 'reboot-smoke'
    members = [(name, (fixture / name).read_bytes())
               for name in ('prepare.py', 'verify.py', 'fail.py')]
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves an existing artifact; fixed metadata is reproducible.
    with output.open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, contents in members:
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, contents)
    print(output)


if __name__ == '__main__':
    main()
