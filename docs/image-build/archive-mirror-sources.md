# Archive-mirror source acquisition

Image-build keeps source identity independent from transport. A reviewed recipe's
canonical URL and SHA-256 remain authoritative; a mirror can only supply bytes that
verify to that SHA-256.

For ordinary HTTPS sources, acquisition order is:

1. the local content-addressed SHA-256 cache;
2. ready authorized archive-mirror providers;
3. the recipe's canonical upstream URL.

`recipe:` sources remain recipe-local and `file:` sources remain explicit local
transports. A corrupt local cache is a hard failure. Mirror misses, authorization or
readiness failures, connection failures, redirects, header/size mismatches and digest
mismatches are recorded as transport observations and may fall through to another
mirror or to canonical upstream. No bearer token is written to image-build state.

## Configuration

Mirror support is optional. It requires a compatible separately installed
`host-identify` (the current 0.3.x line requires Python 3.12) and its credential /
candidate files. The base image-build package remains usable on Python 3.11 when this
feature is not configured.

Pass a JSON file with `--source-mirror-config`, pass its path as the
`source_mirror` argument to `ImageBuild`, or set
`IMAGE_BUILD_SOURCE_MIRROR_CONFIG` for maintained worker entry points:

```json
{
  "schema": 1,
  "credentials_root": "/state/host-identify",
  "public_keyring": "/etc/zog/archive-public-keys.json",
  "issuer": "zog-command-center",
  "audience": "zog-archive-mirror",
  "expected_mirror": "https://archives.example.invalid",
  "collection": "sources",
  "timeout_seconds": 10
}
```

The credentials root is read through
`host_identify.mirror_access.read_access(..., "download", "sources", ...)`. It
must contain the host's archive grant and current `mirror-candidates.json`.
The public keyring is the local Ed25519 verification keyring used for those grants.

Mirror downloads use the current archive-mirror exact-digest route:

```text
GET /collections/sources/archives/SHA256.tar.xz
Authorization: Bearer <short-lived host token>
```

Image-build rejects redirects, requires `X-Archive-SHA256`, checks
`Content-Length` when present, hashes the complete response itself, and only then
atomically installs the payload into its ordinary SHA-256 cache.

Each package attempt retains `source-acquisition.json`. It records the requested
URL/digest and whether the bytes came from `cache`, `recipe`,
`archive-mirror`, or `upstream`, plus sanitized mirror endpoint/result
categories. This observation is not part of recipe or generation identity.

## Current archive-mirror limitation

The current archive-mirror can serve manually imported exact source objects, but its
automatic source collector produces monthly Git-tree archives rather than arbitrary
upstream release tarballs. Therefore this image-build pass makes the read path usable
now; automatic population of exact reviewed URL+SHA-256 recipe inputs is the next
archive-mirror implementation milestone.
