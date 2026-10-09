"""Run with PYTHONPATH=src:tests python3 tests/rehearse.py NEW_DIRECTORY."""
import json
import platform
import subprocess
import sys
from pathlib import Path

from zog.host_install.image import inspect, install
from zog.host_install.manifest import MIB
from support import artifacts


def main():
    base = Path(sys.argv[1]).absolute()
    base.mkdir(mode=0o700)
    m = artifacts(base / "artifacts")
    result = install(m, base / "artifacts", base / "operation", 322 * MIB)
    report = {"fixture": "synthetic; no kernel or EFI binaries; not bootable",
              "python": platform.python_version(), "disk_bytes": 322 * MIB,
              "inspection": inspect(base / "operation"), "commands": []}
    commands = [["partx", "--raw", "--noheadings", "--output", "NR,START,SECTORS,NAME,UUID", result["disk_image"]],
                ["blkid", "-p", str(base / "artifacts/esp.img")]]
    commands += [["e2fsck", "-f", "-n", str(base / "operation" / name)]
                 for name in ("rootfs.img", "HOST-B.img", "STATE.img", "APPLICATIONS.img")]
    for command in commands:
        run = subprocess.run(command, capture_output=True, text=True)
        report["commands"].append({"argv": command, "exit_code": run.returncode,
                                    "stdout": run.stdout, "stderr": run.stderr})
        if run.returncode:
            print(json.dumps(report, indent=2))
            return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
