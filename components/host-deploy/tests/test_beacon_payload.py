import os
import io
import shutil
import zipfile
from pathlib import Path
import pytest
from zog.host_deploy.beacon_payload import payload

SOURCES = Path(os.environ.get("HOST_DEPLOY_SOURCE_DIRECTORY", Path(__file__).resolve().parents[2] / "dependencies/zog144"))

def test_payload_is_deterministic_and_contains_only_reviewed_files(tmp_path):
    first = payload(SOURCES)
    assert payload(SOURCES) == first
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert "host-discover/src/zog/host_discover/daemon.py" in names
        assert "host-identify/src/zog/host_identify/signatures.py" in names
        assert "host-install/src/zog/host_install/state_admission.py" in names
        assert "beacon-source-versions.json" in names
        assert not any(".version-share" in n or "tests/" in n or n.endswith("README.md") for n in names)

def test_changed_or_missing_source_refused_before_remote_upload(tmp_path):
    for name in ("host-identify", "host-install", "host-discover"):
        shutil.copytree(SOURCES / name, tmp_path / name, ignore=shutil.ignore_patterns(".version-share", ".git"))
    (tmp_path / "host-discover/src/zog/host_discover/daemon.py").write_text("changed")
    with pytest.raises(ValueError, match="differs from pinned"):
        payload(tmp_path)
    with pytest.raises(ValueError, match="Missing pinned"):
        payload(tmp_path / "missing")

def test_symlink_input_refused(tmp_path):
    (tmp_path / "host-identify").symlink_to(SOURCES / "host-identify", target_is_directory=True)
    (tmp_path / "host-install").symlink_to(SOURCES / "host-install", target_is_directory=True)
    (tmp_path / "host-discover").symlink_to(SOURCES / "host-discover", target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        payload(tmp_path)
