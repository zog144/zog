"""Authenticated archive-mirror access for exact source bytes.

Mirror transport is deliberately separate from recipe identity. Recipes continue to
name the canonical URL and SHA-256; this module only supplies identical bytes when a
ready authorized mirror already has that digest.
"""
import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ImageBuildError
from .filesystem import digest as file_digest


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class MirrorFetch:
    endpoint: str | None
    attempts: tuple

    @property
    def satisfied(self):
        return self.endpoint is not None


class ArchiveMirrorSource:
    def __init__(self, configuration, *, access_reader=None, opener=None):
        self._configuration = _validate(configuration)
        self._access_reader = access_reader
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    def configuration(self):
        """Stable non-secret policy bound into durable image-build pipelines."""
        return dict(self._configuration)

    def _keys(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as error:
            raise ImageBuildError(
                "archive-mirror access requires host-identify dependencies"
            ) from error
        path = Path(self._configuration["public_keyring"])
        if path.is_symlink() or not path.is_file():
            raise ImageBuildError("archive-mirror public keyring is missing or unsafe")
        try:
            value = json.loads(path.read_text())
            if (
                set(value) != {"version", "keys"}
                or value["version"] != 1
                or not isinstance(value["keys"], dict)
                or not value["keys"]
            ):
                raise ValueError
            return {
                name: Ed25519PublicKey.from_public_bytes(
                    base64.b64decode(encoded, validate=True)
                )
                for name, encoded in value["keys"].items()
            }
        except (OSError, ValueError, TypeError, KeyError, binascii.Error) as error:
            raise ImageBuildError("invalid archive-mirror public keyring") from error

    def _access(self):
        reader = self._access_reader
        if reader is None:
            try:
                from zog.host_identify.mirror_access import read_access
            except ImportError as error:
                raise ImageBuildError(
                    "configured archive-mirror access requires host-identify"
                ) from error
            reader = read_access
        c = self._configuration
        return reader(
            c["credentials_root"],
            self._keys(),
            c["issuer"],
            c["audience"],
            "download",
            c["collection"],
            c["expected_mirror"],
        )

    def fetch(self, expected_sha256, destination):
        """Try ready authorized mirrors in order; never return unverified bytes."""
        if not isinstance(expected_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_sha256
        ):
            raise ImageBuildError("invalid source digest for archive-mirror")
        destination = Path(destination)
        attempts = []
        try:
            access = self._access()
        except Exception:
            return MirrorFetch(None, ({"result": "discovery-unavailable"},))
        token = access.get("token")
        endpoints = access.get("endpoints")
        if not isinstance(token, str) or not isinstance(endpoints, list):
            return MirrorFetch(None, ({"result": "discovery-unavailable"},))
        for endpoint in endpoints:
            destination.unlink(missing_ok=True)
            if not isinstance(endpoint, str):
                attempts.append({"result": "invalid-endpoint"})
                continue
            origin = endpoint.rstrip("/")
            url = (
                f"{origin}/collections/{self._configuration['collection']}"
                f"/archives/{expected_sha256}.tar.xz"
            )
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/octet-stream",
                },
            )
            try:
                with self._opener.open(
                    request, timeout=self._configuration["timeout_seconds"]
                ) as response:
                    if response.geturl() != url:
                        attempts.append({"endpoint": origin, "result": "redirect"})
                        continue
                    if response.headers.get("X-Archive-SHA256") != expected_sha256:
                        attempts.append(
                            {"endpoint": origin, "result": "header-mismatch"}
                        )
                        continue
                    size_header = response.headers.get("Content-Length")
                    try:
                        expected_size = (
                            int(size_header) if size_header is not None else None
                        )
                    except ValueError:
                        attempts.append(
                            {"endpoint": origin, "result": "size-mismatch"}
                        )
                        continue
                    total = 0
                    with destination.open("wb") as output:
                        while block := response.read(1024 * 1024):
                            total += len(block)
                            output.write(block)
                    if expected_size is not None and expected_size != total:
                        destination.unlink(missing_ok=True)
                        attempts.append(
                            {"endpoint": origin, "result": "size-mismatch"}
                        )
                        continue
                    if file_digest(destination) != expected_sha256:
                        destination.unlink(missing_ok=True)
                        attempts.append(
                            {"endpoint": origin, "result": "digest-mismatch"}
                        )
                        continue
                    attempts.append({"endpoint": origin, "result": "hit"})
                    return MirrorFetch(origin, tuple(attempts))
            except urllib.error.HTTPError as error:
                destination.unlink(missing_ok=True)
                result = (
                    "not-found"
                    if error.code == 404
                    else "redirect"
                    if 300 <= error.code < 400
                    else "unavailable"
                )
                attempts.append({"endpoint": origin, "result": result})
            except (urllib.error.URLError, TimeoutError, OSError):
                destination.unlink(missing_ok=True)
                attempts.append({"endpoint": origin, "result": "unavailable"})
        return MirrorFetch(None, tuple(attempts))


def _validate(value):
    required = {
        "schema",
        "credentials_root",
        "public_keyring",
        "issuer",
        "audience",
        "expected_mirror",
        "collection",
        "timeout_seconds",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != 1
    ):
        raise ImageBuildError("unsupported archive-mirror source configuration")
    for key in ("credentials_root", "public_keyring"):
        if not isinstance(value[key], str) or not Path(value[key]).is_absolute():
            raise ImageBuildError(f"archive-mirror {key} must be absolute")
    for key in ("issuer", "audience"):
        if (
            not isinstance(value[key], str)
            or not value[key]
            or len(value[key]) > 512
            or any(ord(c) < 32 for c in value[key])
        ):
            raise ImageBuildError(f"invalid archive-mirror {key}")
    if not isinstance(value["collection"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,63}", value["collection"]
    ):
        raise ImageBuildError("invalid archive-mirror collection")
    if type(value["timeout_seconds"]) not in (int, float) or not (
        0 < value["timeout_seconds"] <= 300
    ):
        raise ImageBuildError("invalid archive-mirror timeout")
    parsed = urlsplit(value["expected_mirror"])
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ImageBuildError(
            "archive-mirror expected_mirror must be an HTTPS origin"
        )
    return json.loads(json.dumps(value))


def configured_source_mirror(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError) as error:
        raise ImageBuildError(
            "cannot read archive-mirror source configuration"
        ) from error
    return ArchiveMirrorSource(value)


def source_mirror_from_environment():
    path = os.environ.get("IMAGE_BUILD_SOURCE_MIRROR_CONFIG")
    return configured_source_mirror(path) if path else None
