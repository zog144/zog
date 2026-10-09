"""Create portable local source definitions for the library/consumer acceptance pair."""

import hashlib
from pathlib import Path


def create(destination):
    destination = Path(destination)
    definitions = {
        "number-library": {
            "files": {
                "number.c": "int zog_number(void) { return 42; }\n",
                "number.h": "int zog_number(void);\n",
            },
            "dependencies": {"build": [], "runtime": []},
            "steps": {
                "build": [
                    ["cc", "-c", "number.c", "-o", "number.o"],
                    ["ar", "rcs", "libzog-number.a", "number.o"],
                ],
                "install": [
                    [
                        "/bin/sh",
                        "-c",
                        'mkdir -p "$DESTDIR/usr/include" "$DESTDIR/usr/lib" && cp number.h "$DESTDIR/usr/include/zog-number.h" && cp libzog-number.a "$DESTDIR/usr/lib/"',
                    ]
                ],
            },
            "outputs": ["usr/include/zog-number.h", "usr/lib/libzog-number.a"],
        },
        "number-print": {
            "files": {
                "number-print.c": '#include <stdio.h>\n#include <zog-number.h>\nint main(void) { printf("%d\\n", zog_number()); return 0; }\n'
            },
            "dependencies": {"build": ["number-library"], "runtime": []},
            "steps": {
                "build": [
                    [
                        "cc",
                        "-static",
                        "-I/usr/include",
                        "number-print.c",
                        "/usr/lib/libzog-number.a",
                        "-o",
                        "number-print",
                    ]
                ],
                "test": [["./number-print"]],
                "install": [
                    [
                        "/bin/sh",
                        "-c",
                        'mkdir -p "$DESTDIR/usr/bin" && cp number-print "$DESTDIR/usr/bin/"',
                    ]
                ],
            },
            "outputs": ["usr/bin/number-print"],
        },
    }
    for name, definition in definitions.items():
        directory = destination / name
        directory.mkdir(parents=True)
        sources = []
        for filename, content in definition["files"].items():
            path = directory / filename
            path.write_text(content)
            sources.append(
                {
                    "url": path.resolve().as_uri(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "destination": filename,
                    "archive": False,
                }
            )
        for filename, value in {
            "sources.py": sources,
            "dependencies.py": definition["dependencies"],
            "build.py": definition["steps"],
            "produce-manifest.py": definition["outputs"],
        }.items():
            (directory / filename).write_text(repr(value) + "\n")
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    create(parser.parse_args().destination)
