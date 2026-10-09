# Data only; parsed with ast.literal_eval.
{'project': 'libxcrypt',
 'stage_id': 'final',
 'base_contract': 'Accepted Gperf/MarkupSafe/Jinja2 generation supplies self-hosted compiler, '
                  'Make, Meson/Ninja, CMake, Python, pkgconf, OpenSSL, zlib, xz and zstd. Exact '
                  'inherited outputs bound by base-components.',
 'patches': [{'id': 'c23-qualifiers',
              'origin': 'upstream',
              'commit': '174c24d6e87aeae631bc0a7bb1ba983cf8def4de',
              'author': 'Stanislav Zidek',
              'source': {'url': 'https://github.com/besser82/libxcrypt/commit/174c24d6e87aeae631bc0a7bb1ba983cf8def4de.patch',
                         'sha256': 'f10d86f3155e9c34e9a1d50db0e86ec6aa10a111939642623b421f5998119049',
                         'destination': 'patches/c23-qualifiers.patch',
                         'archive': False},
              'applies_to': {'version': '4.5.2', 'stage': 'final'},
              'reason': 'C23 strchr qualifier preservation rejects casts to const for mutable '
                        'result pointers.',
              'order': 1,
              'strip': 1,
              'fuzz': 0,
              'files': [{'path': 'lib/crypt-gost-yescrypt.c',
                         'before_sha256': 'a4bca98dccf0b74a1a3d027faaef7c79209681b6b8908cf6dfd44ff721255dad',
                         'after_sha256': '1cf5465bd2393615d2c7fd9f54bc3203b5ddf2d6831f32d1b8cd3651b0d5f62f'},
                        {'path': 'lib/crypt-sm3-yescrypt.c',
                         'before_sha256': '9ceeee7cbcbf757f09237c94388aa18e01532e5ced60aba454bd8b16141c5519',
                         'after_sha256': 'b4a3610b3d6c925ee570f4a1a34a411f7db772bacd3aa2bdf6ad6100f9357763'}],
              'review': 'Unmodified merged upstream commit; both source files retain explicit '
                        'permissive notices. Zero-fuzz application verified; live acceptance '
                        'pending.',
              'retirement': 'Remove when a pinned release already includes the upstream fix.'}]}
