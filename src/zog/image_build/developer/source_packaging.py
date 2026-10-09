"""Extract source RPM packaging as inert evidence; never execute a spec or scriptlet."""

import subprocess
from pathlib import Path
from ..errors import ImageBuildError
from ..metadata import relative


def extract(source_rpm, destination):
    source_rpm, destination = Path(source_rpm), Path(destination)
    if destination.exists():
        raise ImageBuildError("source packaging destination must be new")
    destination.mkdir(parents=True)
    payload = destination / "payload.cpio"
    with payload.open("wb") as stream:
        subprocess.run(
            ["rpm2cpio", str(source_rpm)], stdout=stream, check=True, timeout=120
        )
    extracted = []
    try:
        with payload.open("rb") as stream:

            def read_exact(count):
                value = stream.read(count)
                if len(value) != count:
                    raise ImageBuildError("truncated source RPM payload")
                return value

            while True:
                header = read_exact(110)
                if header[:6] not in (b"070701", b"070702"):
                    raise ImageBuildError("unsupported source RPM cpio format")
                try:
                    fields = [int(header[i : i + 8], 16) for i in range(6, 110, 8)]
                except ValueError as error:
                    raise ImageBuildError("invalid cpio header") from error
                mode, links, size, name_size = (
                    fields[1],
                    fields[4],
                    fields[6],
                    fields[11],
                )
                if not 1 <= name_size <= 4096:
                    raise ImageBuildError("invalid cpio filename size")
                raw = read_exact(name_size)
                read_exact((-(110 + name_size)) % 4)
                if raw[-1:] != b"\0":
                    raise ImageBuildError("unterminated cpio filename")
                name = raw[:-1].decode("utf-8")
                if name == "TRAILER!!!":
                    break
                while name.startswith("./"):
                    name = name[2:]
                relative(name)
                target = destination / "files" / name
                if name in extracted or mode & 0o170000 != 0o100000 or links != 1:
                    raise ImageBuildError(
                        "source packaging accepts unique regular files only"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    remaining = size
                    while remaining:
                        chunk = read_exact(min(remaining, 1024 * 1024))
                        output.write(chunk)
                        remaining -= len(chunk)
                read_exact((-size) % 4)
                extracted.append(name)
    finally:
        payload.unlink(missing_ok=True)
    return extracted
