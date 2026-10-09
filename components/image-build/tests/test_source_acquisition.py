import hashlib
import io
import urllib.error
from pathlib import Path

import pytest

from zog.image_build.archive_mirror import ArchiveMirrorSource, MirrorFetch
from zog.image_build.errors import ImageBuildError
from zog.image_build.source_acquisition import acquire


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeMirror:
    def __init__(self, data=None, attempts=()):
        self.data = data
        self.attempts = attempts
        self.calls = 0

    def fetch(self, expected, destination):
        self.calls += 1
        if self.data is None:
            return MirrorFetch(None, tuple(self.attempts))
        Path(destination).write_bytes(self.data)
        return MirrorFetch(
            "https://mirror.test",
            ({"endpoint": "https://mirror.test", "result": "hit"},),
        )


def test_cache_short_circuits_mirror(tmp_path):
    data = b"cached"
    expected = sha(data)
    (tmp_path / expected).write_bytes(data)
    mirror = FakeMirror(b"wrong")
    path, record = acquire(
        {"url": "https://upstream.test/a", "sha256": expected, "destination": "a"},
        tmp_path,
        source_mirror=mirror,
    )
    assert path.read_bytes() == data
    assert record["transport"] == "cache"
    assert mirror.calls == 0


def test_mirror_hit(tmp_path):
    data = b"mirror"
    expected = sha(data)
    mirror = FakeMirror(data)
    path, record = acquire(
        {"url": "https://upstream.invalid/a", "sha256": expected, "destination": "a"},
        tmp_path,
        source_mirror=mirror,
    )
    assert path.read_bytes() == data
    assert record["transport"] == "archive-mirror"
    assert record["endpoint"] == "https://mirror.test"


def test_file_source_bypasses_mirror(tmp_path):
    data = b"upstream"
    upstream = tmp_path / "upstream"
    upstream.write_bytes(data)
    expected = sha(data)
    mirror = FakeMirror(None, ({"endpoint": "https://mirror.test", "result": "not-found"},))
    path, record = acquire(
        {"url": upstream.as_uri(), "sha256": expected, "destination": "a"},
        tmp_path / "cache",
        source_mirror=mirror,
    )
    assert path.read_bytes() == data
    assert record["transport"] == "upstream"
    assert mirror.calls == 0


def test_https_mirror_miss_then_upstream(monkeypatch, tmp_path):
    data = b"upstream"
    expected = sha(data)
    mirror = FakeMirror(
        None, ({"endpoint": "https://mirror.test", "result": "not-found"},)
    )

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def geturl(self):
            return "https://upstream.test/a"

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(data))
    path, record = acquire(
        {"url": "https://upstream.test/a", "sha256": expected, "destination": "a"},
        tmp_path,
        source_mirror=mirror,
    )
    assert path.read_bytes() == data
    assert record["transport"] == "upstream"
    assert record["mirror_attempts"][0]["result"] == "not-found"


def test_reported_mirror_hit_is_independently_verified(tmp_path):
    expected = sha(b"good")
    mirror = FakeMirror(b"bad")
    with pytest.raises(ImageBuildError, match="checksum mismatch"):
        acquire(
            {"url": "https://upstream.test/a", "sha256": expected, "destination": "a"},
            tmp_path,
            source_mirror=mirror,
        )
    assert not (tmp_path / expected).exists()


def test_recipe_bytes_bypass_mirror(tmp_path):
    data = b"recipe"
    expected = sha(data)
    bundled = tmp_path / "bundled"
    bundled.write_bytes(data)
    mirror = FakeMirror(b"wrong")
    path, record = acquire(
        {"url": "recipe:bundled", "sha256": expected, "destination": "a"},
        tmp_path / "cache",
        bundled=bundled,
        source_mirror=mirror,
    )
    assert path.read_bytes() == data
    assert record["transport"] == "recipe"
    assert mirror.calls == 0


def test_corrupt_cache_is_a_hard_failure(tmp_path):
    expected = sha(b"good")
    (tmp_path / expected).write_bytes(b"bad")
    with pytest.raises(ImageBuildError, match="corrupt source cache"):
        acquire(
            {"url": "https://upstream.test/a", "sha256": expected, "destination": "a"},
            tmp_path,
        )


def configuration(tmp_path):
    return {
        "schema": 1,
        "credentials_root": str(tmp_path.resolve()),
        "public_keyring": str((tmp_path / "keys.json").resolve()),
        "issuer": "issuer",
        "audience": "audience",
        "expected_mirror": "https://cluster.test",
        "collection": "sources",
        "timeout_seconds": 5,
    }


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, url, digest):
        super().__init__(data)
        self._url = url
        self.headers = Headers(
            {"X-Archive-SHA256": digest, "Content-Length": str(len(data))}
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def geturl(self):
        return self._url


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _ConfiguredMirror(ArchiveMirrorSource):
    def __init__(self, config, access, opener):
        super().__init__(
            config, access_reader=lambda *args: access, opener=opener
        )
        self._access_value = access

    def _access(self):
        return self._access_value


def test_archive_mirror_tries_next_endpoint_without_recording_token(tmp_path):
    data = b"archive"
    expected = sha(data)
    url2 = f"https://two.test/collections/sources/archives/{expected}.tar.xz"
    first = urllib.error.HTTPError(
        "https://one.test/x", 404, "missing", {}, None
    )
    opener = Opener([first, Response(data, url2, expected)])
    mirror = _ConfiguredMirror(
        configuration(tmp_path),
        {"endpoints": ["https://one.test", "https://two.test"], "token": "secret"},
        opener,
    )
    result = mirror.fetch(expected, tmp_path / "download")
    assert result.satisfied
    assert result.endpoint == "https://two.test"
    assert [item["result"] for item in result.attempts] == ["not-found", "hit"]
    assert opener.requests[1][0].headers["Authorization"] == "Bearer secret"
    assert "secret" not in repr(result)


def test_archive_mirror_rejects_wrong_digest_header(tmp_path):
    data = b"archive"
    expected = sha(data)
    url = f"https://one.test/collections/sources/archives/{expected}.tar.xz"
    opener = Opener([Response(data, url, "0" * 64)])
    mirror = _ConfiguredMirror(
        configuration(tmp_path),
        {"endpoints": ["https://one.test"], "token": "secret"},
        opener,
    )
    result = mirror.fetch(expected, tmp_path / "download")
    assert not result.satisfied
    assert result.attempts[0]["result"] == "header-mismatch"
    assert not (tmp_path / "download").exists()
