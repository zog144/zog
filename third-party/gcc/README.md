# GCC-derived patch sources

This directory contains third-party-derived source material needed to reproduce
specific Zog image-build recipes. Files here are deliberately separated from
Zog first-party code and are **not** relicensed under Zog's
`BSD-3-Clause OR GPL-3.0-only` first-party grant.

## cpython-gcc15.patch

`patches/cpython-gcc15.patch` is a Zog-maintained GCC 15 test-suite backport
for GCC's CPython static-analyzer plugin.

It is derived from upstream GCC work by:

- David Malcolm, commit
  `c2c64cfcd07b1060a6c16d1695972938ea643c1f`
- Jakub Jelinek, follow-up commit
  `bc615c0d69e5587f7336c55cfb61f51f74429b60`

Upstream repository:

`https://github.com/gcc-mirror/gcc`

The exact patch retained here adapts that work to GCC 15.3.0: it keeps GCC 15's
callback-registration and diagnostic interfaces rather than GCC 16's pub/sub
interfaces, retains the upstream CPython object modeling, anonymous-field
traversal and guards, and excludes the unrelated upstream compiler-code
assertions.

This exact adapted file is maintained by Zog as third-party-derived GCC source.
Applicable GCC upstream terms apply; image-build records this source scope as
`GPL-3.0-or-later`. Attribution to the upstream authors above describes the
source work from which this adaptation was made; neither author is represented
as having authored the exact Zog-adapted patch bytes.

Expected SHA-256 for `patches/cpython-gcc15.patch`:

`5b302894ccebee465679e8770b6e60de2356ead428674b4873aaa1081fe18031`

Image-build must retrieve this file through an immutable public Git commit and
verify its SHA-256 before use.
