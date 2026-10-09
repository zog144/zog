# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'libxcrypt',
 'version': '4.5.2',
 'source': {'url': 'https://github.com/besser82/libxcrypt/releases/download/v4.5.2/libxcrypt-4.5.2.tar.xz',
            'sha256': '71513a31c01a428bccd5367a32fd95f115d6dac50fb5b60c779d5c7942aec071'},
 'status': 'declared',
 'expression': 'LGPL-2.1-or-later',
 'scope': 'Primary project/library/tool terms; component detail remains subject to release review.',
 'evidence': [{'path': 'libxcrypt-4.5.2/COPYING.LIB',
               'sha256': 'dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551',
               'source_sha256': '71513a31c01a428bccd5367a32fd95f115d6dac50fb5b60c779d5c7942aec071'},
              {'path': 'libxcrypt-4.5.2/LICENSING',
               'sha256': '9144e66d8140feb84f0e4e344906ac425378896320032e0248567ef195cf0135',
               'source_sha256': '71513a31c01a428bccd5367a32fd95f115d6dac50fb5b60c779d5c7942aec071'},
              {'path': 'libxcrypt-4.5.2/lib/crypt-gost-yescrypt.c',
               'sha256': 'a4bca98dccf0b74a1a3d027faaef7c79209681b6b8908cf6dfd44ff721255dad',
               'source_sha256': '71513a31c01a428bccd5367a32fd95f115d6dac50fb5b60c779d5c7942aec071'},
              {'path': 'libxcrypt-4.5.2/lib/crypt-sm3-yescrypt.c',
               'sha256': '9ceeee7cbcbf757f09237c94388aa18e01532e5ced60aba454bd8b16141c5519',
               'source_sha256': '71513a31c01a428bccd5367a32fd95f115d6dac50fb5b60c779d5c7942aec071'}],
 'components': [{'scope': 'Auxiliary files, bundled tests and licensing exceptions',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Retained archive and source notices; complete per-file review pending. '
                          'libxcrypt LICENSING enumerates additional terms; PCRE2 terms retained '
                          'without blanket SPDX simplification.'}],
 'patches': [{'scope': 'c23-qualifiers: '
                       'f10d86f3155e9c34e9a1d50db0e86ec6aa10a111939642623b421f5998119049',
              'expression': 'LicenseRef-libxcrypt-yescrypt-notices',
              'status': 'declared',
              'notes': 'Unmodified upstream patch by Stanislav Zidek, commit '
                       '174c24d6e87aeae631bc0a7bb1ba983cf8def4de. Both affected source files '
                       'retain permission to redistribute/modify and warranty disclaimers; '
                       'original file notices are retained as hashed evidence. Patch mail itself '
                       'has attribution but no separate license header.'}],
 'notes': ['Exact release archive and original notices inspected 2026-10-07.',
           'Final recipe applies downloaded c23-qualifiers patch. Original license evidence hashes '
           'remain unchanged; verified patched content is tracked separately.']}
