# GCC 15 test-only backports

These patches change test fixtures, not GCC compiler implementation code. The
patch payloads are no longer retained in the private image-build repository.
Image-build retrieves exact reviewed bytes from immutable public Zog commit:

`8aeb6ad76402a9f91d6408e445190b4c03dd69f8`

Public source directory:

`third-party/gcc/patches/`

- `strchr-c23.patch`: exact test-file diff from David Malcolm's upstream GCC
  commit `06f094958161f8c31746b33164a35820eecef4ee`; no Zog adaptation.
- `cpython-gcc15.patch`: Zog-maintained GCC 15 adaptation derived from David
  Malcolm's `c2c64cfcd07b1060a6c16d1695972938ea643c1f` and Jakub Jelinek's
  follow-up `bc615c0d69e5587f7336c55cfb61f51f74429b60`. It retains GCC 15's
  callback-registration and stmt_finder diagnostics interfaces instead of GCC
  16's pub/sub interfaces, carries the upstream Python object modeling,
  anonymous-field traversal and guards, and excludes the unrelated upstream
  compiler-code assertions.

Upstream repository: `https://github.com/gcc-mirror/gcc`.

GCC upstream terms apply; see the exact GCC 15.3.0 source archive's COPYING3.
These patches are not Zog-licensed first-party source. The public Zog
`third-party/gcc/README.md` records attribution and the distinction between the
exact upstream diff and the GCC-15-specific adaptation.

Normal builds download these sources by immutable URL and verify the exact hashes
below before applying them with zero fuzz. The monthly pin records the same URLs
and hashes.

| Public patch | SHA-256 |
|---|---|
| `cpython-gcc15.patch` | `5b302894ccebee465679e8770b6e60de2356ead428674b4873aaa1081fe18031` |
| `strchr-c23.patch` | `312cbc23d95b25d17141f2b90dec8a273b2eaacb21d2e0a8bc07f64d5b26baaf` |

Reassess both backports whenever the GCC or Python pin changes.
