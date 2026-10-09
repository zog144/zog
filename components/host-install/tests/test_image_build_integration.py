"""Real cross-program tests; no verifier stubs in this module.

Set HOST_INSTALL_FIXTURES to a reviewed image-build fixture directory and put the
matching reviewed image-build source on PYTHONPATH. Otherwise these are skipped.
"""
import json
import os
import tempfile
import shutil
import subprocess
import sys
import uuid
import unittest
from pathlib import Path

from zog.host_install.artifact import stage
from zog.host_install import InstallError
from zog.host_install.filesystem import build_root_fixture

VALID_ID = "98b3240f21ececf7f4100950a18b769f0c5fb485971a15587af2987697d6c658"
FIXTURES = os.environ.get("HOST_INSTALL_FIXTURES")


@unittest.skipUnless(FIXTURES, "reviewed image-build source/fixtures not supplied")
class ImageBuildIntegrationTests(unittest.TestCase):
    def test_valid_fixture_stages_but_is_not_installable(self):
        with tempfile.TemporaryDirectory() as temp:
            result = stage(Path(FIXTURES) / "valid", VALID_ID, Path(temp) / "operation")
            self.assertEqual(result["status"], "staged-for-offline-tests")
            self.assertFalse(result["installable"])
            self.assertFalse(result["source_readiness"]["installable"])
            self.assertEqual((Path(temp) / "operation/rootfs/tmp").stat().st_mode & 0o7777, 0o1777)

    @unittest.skipUnless(os.geteuid() == 0 and os.getegid() == 0 and
                         all(shutil.which(t) for t in ("mkfs.ext4", "e2fsck", "debugfs")),
                         "root filesystem integration requires root and e2fsprogs")
    def test_real_artifact_populates_ext4(self):
        with tempfile.TemporaryDirectory() as temp:
            op = Path(temp) / "staging"
            stage(Path(FIXTURES) / "valid", VALID_ID, op)
            fs = Path(temp) / "filesystem"
            result = build_root_fixture(op, fs, 64, str(uuid.uuid4()))
            self.assertFalse(result["installable"])
            path = "usr/share/host-install-fixture/README"
            readback = subprocess.run(["debugfs", "-R", f"cat /{path}", str(fs / "rootfs.img")],
                                      check=True, capture_output=True)
            self.assertEqual(readback.stdout, (op / "rootfs" / path).read_bytes())
            metadata = subprocess.run(["debugfs", "-R", "stat /tmp", str(fs / "rootfs.img")],
                                      check=True, capture_output=True, text=True)
            self.assertRegex(metadata.stdout, r"Mode:\s+01777")

    def rejected(self, name):
        fixture = Path(FIXTURES) / name
        expectations = json.loads((Path(FIXTURES) / "expectations.json").read_text())
        expected = next(c["expected_id"] for c in expectations["cases"] if c["directory"] == name)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "operation"
            # First verify that the integration package is actually importable;
            # a missing dependency is a test error, never an expected rejection.
            import zog.image_build.host_export
            zog.image_build.host_export.verify(Path(FIXTURES) / "valid", VALID_ID)
            messages = {"corrupt-payload": "payload hash/size mismatch",
                        "unsafe-path": "unsafe artifact path",
                        "false-readiness": "invalid readiness or storage claims"}
            with self.assertRaisesRegex(InstallError, messages[name]):
                stage(fixture, expected, output)
            self.assertFalse(output.exists(), "unsafe fixture reached extraction staging")

    def test_corrupt_payload_rejected(self):
        self.rejected("corrupt-payload")

    def test_unsafe_path_rejected(self):
        self.rejected("unsafe-path")

    def test_false_readiness_rejected(self):
        self.rejected("false-readiness")

    def test_cli_rejection_is_structured(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, "-m", "zog.host_install", "stage-artifact",
                str(Path(FIXTURES) / "corrupt-payload"), "--expected-id", VALID_ID,
                "--operation", str(Path(temp) / "operation")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stderr)["ok"])
            self.assertIn("payload hash/size mismatch", json.loads(result.stderr)["error"])
