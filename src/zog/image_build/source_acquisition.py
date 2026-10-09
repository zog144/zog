"""Verified source acquisition policy: cache, archive-mirror, then canonical URL."""
import shutil
import urllib.request
from pathlib import Path

from .errors import ImageBuildError
from .filesystem import digest


def _upstream(url, destination):
    with urllib.request.urlopen(url, timeout=60) as response, destination.open(
        "wb"
    ) as output:
        if response.geturl().split(":", 1)[0] not in ("https", "file"):
            raise ImageBuildError("source redirected to unsupported transport")
        shutil.copyfileobj(response, output)


def acquire(source, cache, *, bundled=None, source_mirror=None):
    """Return a verified cache path and a non-secret transport observation."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    expected = source["sha256"]
    payload = cache / expected
    base = {
        "url": source["url"],
        "sha256": expected,
        "destination": source["destination"],
    }
    if payload.exists():
        if digest(payload) != expected:
            raise ImageBuildError(f"corrupt source cache: {payload.name}")
        return payload, {**base, "transport": "cache"}

    temporary = payload.with_suffix(".download")
    mirror_attempts = ()
    try:
        if bundled is not None:
            shutil.copyfile(bundled, temporary)
            record = {**base, "transport": "recipe"}
        else:
            mirror = None
            # file: is an explicit local transport and recipe: was handled above.
            if source_mirror is not None and source["url"].startswith("https:"):
                mirror = source_mirror.fetch(expected, temporary)
                mirror_attempts = mirror.attempts
            if mirror is not None and mirror.satisfied:
                record = {
                    **base,
                    "transport": "archive-mirror",
                    "endpoint": mirror.endpoint,
                    "mirror_attempts": list(mirror_attempts),
                }
            else:
                temporary.unlink(missing_ok=True)
                _upstream(source["url"], temporary)
                record = {**base, "transport": "upstream"}
                if mirror_attempts:
                    record["mirror_attempts"] = list(mirror_attempts)
        if digest(temporary) != expected:
            raise ImageBuildError(f"source checksum mismatch: {source['url']}")
        temporary.replace(payload)
        return payload, record
    finally:
        temporary.unlink(missing_ok=True)
