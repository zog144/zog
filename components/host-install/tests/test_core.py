import io
import json
import os
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from zog.host_install import InstallError
from zog.host_install.artifact import extract, stage, verify_tree
from zog.host_install.image import inspect, install
from zog.host_install.filesystem import build_root_fixture
from zog.host_install.layout import plan, regions
from zog.host_install.manifest import MIB, parse, validate
from zog.host_install.preflight import assess
from support import artifacts, inventory, manifest


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(manifest())["schema"], 1)

    def test_rejections(self):
        for field, value in (("schema", 2), ("schema", True), ("architecture", "aarch64")):
            with self.subTest(field=field, value=value):
                m = manifest(); m[field] = value
                with self.assertRaises(InstallError): validate(m)
        for path in ("/root.img", "../root.img", "a/../root.img", "a//root.img"):
            with self.subTest(path=path):
                m = manifest(); m["artifacts"]["rootfs"]["path"] = path
                with self.assertRaises(InstallError): validate(m)

    def test_boot_binding(self):
        m = manifest(); m["boot"]["root_argument"] = "root=/dev/nvme1n1p2"
        with self.assertRaises(InstallError): validate(m)

    def test_duplicate_json(self):
        with self.assertRaises(InstallError): parse('{"schema":1,"schema":1}')

    def test_duplicate_uuids(self):
        m = manifest(); m["layout"]["partitions"][2]["partuuid"] = m["boot"]["root_partuuid"]
        with self.assertRaises(InstallError): validate(m)

    def test_layout_size_and_crc(self):
        m = manifest()
        with self.assertRaises(InstallError): plan(m, 321 * MIB)
        p = plan(m, 322 * MIB)
        for _, data in (regions(p)[1], regions(p)[4]):
            h = bytearray(data[:92]); crc = struct.unpack_from("<I", h, 16)[0]
            struct.pack_into("<I", h, 16, 0)
            self.assertEqual(crc, zlib.crc32(h))
        self.assertEqual(p["partitions"][0]["first_lba"], 2048)
        self.assertLess(p["partitions"][-1]["last_lba"], 322 * MIB // 512 - 33)


class SafetyTests(unittest.TestCase):
    def check(self, inv=None, target="/dev/target", identity="serial:target"):
        return assess(inv or inventory(), target, identity, 322 * MIB)

    def test_safe_report_is_read_only(self):
        self.assertFalse(self.check()["device_writes_enabled"])

    def test_root_disk_rejected_through_lvm(self):
        with self.assertRaisesRegex(InstallError, "running root"):
            self.check(target="/dev/rootdisk", identity="serial:root")

    def test_mount_swap_holder_readonly_missing_identity_and_size(self):
        cases = [(4, "mounts", ["/mnt"]), (4, "mounts", ["[SWAP]"]),
                 (4, "holders", ["dm-1"]), (3, "read_only", True),
                 (3, "identity", None), (3, "size", 100 * MIB)]
        for index, key, value in cases:
            with self.subTest(key=key, value=value):
                inv = inventory(); inv["devices"][index][key] = value
                with self.assertRaises(InstallError): self.check(inv)

    def test_duplicate_identity(self):
        inv = inventory(); inv["devices"][0]["identity"] = "serial:target"
        with self.assertRaises(InstallError): self.check(inv)

    def test_missing_root(self):
        inv = inventory(); inv["root_devnos"] = ["0:99"]
        with self.assertRaises(InstallError): self.check(inv)

    def test_cycle_and_missing_parent(self):
        for parents in (["/dev/target1"], ["/dev/missing"]):
            inv = inventory(); inv["devices"][3]["parents"] = parents
            with self.assertRaises(InstallError): self.check(inv)

    def test_incomplete_snapshot(self):
        inv = inventory(); inv["complete"] = False
        with self.assertRaises(InstallError): self.check(inv)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def tar(self, entries):
        path = self.base / "input.tar"
        with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as out:
            for name, kind, value in entries:
                m = tarfile.TarInfo(name); m.mode = 0o755 if kind == "dir" else 0o644
                if kind == "dir": m.type = tarfile.DIRTYPE
                elif kind == "link": m.type = tarfile.SYMTYPE; m.linkname = value
                elif kind == "hard": m.type = tarfile.LNKTYPE; m.linkname = value
                else: m.size = len(value)
                out.addfile(m, io.BytesIO(value) if kind == "file" else None)
        return path

    def test_absolute_links_preserved_but_not_followed(self):
        source = self.tar([("usr", "dir", None), ("usr/tool", "file", b"data"),
                           ("bin", "link", "/usr")])
        dest = self.base / "out"
        extract(source, dest, 1024)
        verify_tree(source, dest)
        self.assertEqual((dest / "bin").readlink(), Path("/usr"))
        (dest / "usr/tool").write_bytes(b"evil")
        with self.assertRaises(InstallError): verify_tree(source, dest)

    def test_unsafe_archives_rejected_before_destination_created(self):
        cases = [[("../escape", "file", b"x")], [("/escape", "file", b"x")],
                 [("a", "link", "/tmp"), ("a/escape", "file", b"x")],
                 [("a", "file", b"x"), ("a", "file", b"y")],
                 [("a", "hard", "elsewhere")], [("missing/a", "file", b"x")]]
        for entries in cases:
            with self.subTest(entries=entries):
                source = self.tar(entries); dest = self.base / "out"
                with self.assertRaises(InstallError): extract(source, dest, 1024)
                self.assertFalse(dest.exists())

    def test_extraction_limit(self):
        source = self.tar([("large", "file", b"123")])
        with self.assertRaises(InstallError): extract(source, self.base / "out", 2)

    def test_no_existing_destination(self):
        source = self.tar([]); out = self.base / "out"; out.mkdir()
        with self.assertRaises(InstallError): extract(source, out, 1024)

    def test_upstream_adapter_preserves_blockers(self):
        # This is an adapter-unit test, not execution of image-build's verifier.
        source = self.base / "source"; source.mkdir()
        self.tar([("usr", "dir", None), ("usr/tool", "file", b"fixture")]).rename(source / "rootfs.tar")
        m = {"schema": 1, "kind": "host-install-artifact", "ownership_policy": "all-root-v1",
             "artifact_id": "a" * 64, "readiness": {"installable": False, "blockers": ["not ready"]},
             "security": {"verified_boot": False}, "boot_bundle": None,
             "rootfs": {"bytes": (source / "rootfs.tar").stat().st_size}}
        (source / "manifest.json").write_text(json.dumps(m))
        with patch("zog.host_install.artifact.upstream_verify", return_value=m) as verifier:
            result = stage(source, "a" * 64, self.base / "operation")
        self.assertEqual(verifier.call_count, 3)
        self.assertFalse(result["installable"])
        self.assertEqual(result["source_readiness"], m["readiness"])
        if os.geteuid() == 0 and os.getegid() == 0 and all(shutil.which(t) for t in ("mkfs.ext4", "e2fsck", "debugfs")):
            import uuid
            with patch("zog.host_install.filesystem.upstream_verify", return_value=m):
                fs = build_root_fixture(self.base / "operation", self.base / "filesystem", 64, str(uuid.uuid4()))
            self.assertFalse(fs["installable"])
            readback = subprocess.run(["debugfs", "-R", "cat /usr/tool", str(self.base / "filesystem/rootfs.img")],
                                      check=True, capture_output=True)
            self.assertEqual(readback.stdout, b"fixture")

    def test_upstream_snapshot_mutation_rejected(self):
        source = self.base / "source"; source.mkdir()
        self.tar([]).rename(source / "rootfs.tar")
        m = {"schema": 1, "kind": "host-install-artifact", "ownership_policy": "all-root-v1",
             "artifact_id": "b" * 64, "readiness": {"installable": False}, "security": {},
             "boot_bundle": None, "rootfs": {"bytes": 10240}}
        (source / "manifest.json").write_text(json.dumps(m))
        with patch("zog.host_install.artifact.upstream_verify", side_effect=[m, dict(m, artifact_id="changed")]):
            with self.assertRaisesRegex(InstallError, "changed during snapshot"):
                stage(source, "b" * 64, self.base / "operation")
        self.assertEqual(json.loads((self.base / "operation/staging.json").read_text())["status"], "incomplete")

    def test_setid_mode_rejected(self):
        source = self.base / "input.tar"
        with tarfile.open(source, "w", format=tarfile.USTAR_FORMAT) as out:
            m = tarfile.TarInfo("setid"); m.mode = 0o4755
            out.addfile(m, io.BytesIO(b""))
        with self.assertRaises(InstallError): extract(source, self.base / "out", 1024)


@unittest.skipUnless(shutil.which("mkfs.ext4"), "mkfs.ext4 missing")
class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.m = artifacts(self.base / "artifacts")

    def install(self):
        return install(self.m, self.base / "artifacts", self.base / "operation", 322 * MIB)

    def test_real_image_and_external_partition_parser(self):
        result = self.install()
        self.assertEqual(inspect(self.base / "operation")["integrity"], "matched")
        self.assertEqual(result["validation"]["bootability"], "not-tested")
        if shutil.which("partx"):
            output = subprocess.run(["partx", "--raw", "--noheadings", "--output",
                                     "NR,START,SECTORS,NAME,UUID", result["disk_image"]],
                                    check=True, capture_output=True, text=True).stdout
            self.assertEqual(len(output.splitlines()), 5)
            for line, part in zip(output.splitlines(), result["validation"]["partitions"]):
                self.assertEqual(line.split(), [str(part["number"]), str(part["first_lba"]),
                    str(part["last_lba"] - part["first_lba"] + 1), part["role"], part["partuuid"]])
        with self.assertRaises(FileExistsError): self.install()

    def test_corrupt_partition_rejected(self):
        self.install()
        with (self.base / "operation/disk.img").open("r+b") as out:
            out.seek(2 * MIB); out.write(b"corrupt")
        with self.assertRaisesRegex(InstallError, "partition content"):
            inspect(self.base / "operation")

    def test_corrupt_backup_gpt_rejected(self):
        self.install()
        with (self.base / "operation/disk.img").open("r+b") as out:
            out.seek(-512, 2); out.write(b"BROKEN")
        with self.assertRaisesRegex(InstallError, "GPT mismatch"):
            inspect(self.base / "operation")

    def test_wrong_hash_blocks_disk_creation(self):
        self.m["artifacts"]["rootfs"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(InstallError, "SHA-256"): self.install()
        self.assertFalse((self.base / "operation/disk.img").exists())
        self.assertEqual(json.loads((self.base / "operation/operation.json").read_text())["status"], "incomplete")

    def test_failure_after_write_retains_incomplete_marker(self):
        with patch("zog.host_install.image.inspect", side_effect=InstallError("injected validation failure")):
            with self.assertRaises(InstallError): self.install()
        with self.assertRaisesRegex(InstallError, "incomplete"):
            inspect(self.base / "operation")

    def test_filesystem_uuid_mismatch(self):
        self.m["layout"]["partitions"][1]["filesystem_uuid"] = self.m["layout"]["partitions"][2]["filesystem_uuid"]
        # Keep UUID uniqueness while mismatching the actual ext4 superblock.
        import uuid
        self.m["layout"]["partitions"][2]["filesystem_uuid"] = str(uuid.uuid4())
        with self.assertRaisesRegex(InstallError, "UUID mismatch"): self.install()

    def test_output_symlink_not_followed(self):
        sentinel = self.base / "sentinel"; sentinel.write_text("unchanged")
        (self.base / "operation").symlink_to(sentinel)
        with self.assertRaises(FileExistsError): self.install()
        self.assertEqual(sentinel.read_text(), "unchanged")

    def test_artifact_symlink_rejected(self):
        root = self.base / "artifacts/rootfs.img"
        root.rename(root.with_suffix(".original")); root.symlink_to(root.with_suffix(".original"))
        with self.assertRaisesRegex(InstallError, "symlink"): self.install()


if __name__ == "__main__":
    unittest.main()
