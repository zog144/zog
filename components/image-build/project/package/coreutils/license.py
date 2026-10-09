# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'coreutils',
 'version': '9.11',
 'source': {'url': 'https://ftp.gnu.org/gnu/coreutils/coreutils-9.11.tar.xz',
            'sha256': '394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3'},
 'status': 'declared',
 'expression': 'GPL-3.0-or-later',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'coreutils-9.11/COPYING',
               'sha256': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986',
               'source_sha256': '394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3'},
              {'path': 'coreutils-9.11/README',
               'sha256': 'f94ae5ca23adaff5f68dbd5da5a9e19c0696de4f7dd88b226d077faf3847d17f',
               'source_sha256': '394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3'},
              {'path': 'coreutils-9.11/src/ls.c',
               'sha256': '4b3b8f7f7b1eb161672f4fa7fc6eed7146afc94bfb1a2ab14b6c1c96030aacb1',
               'source_sha256': '394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3'}],
 'components': [{'scope': 'Other included files, documentation, generated code and bundled subprojects',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Complete per-file/stage scope review remains required; primary declaration '
                          'is not a blanket grant.'}],
 'patches': [],
 'notes': ['Inspected exact release archive on 2026-09-27; source and evidence hashes are bound to this '
           'version.',
           'Declared is not release-reviewed. Per-component notices, exceptions and '
           'corresponding-source obligations require final review.',
           'LicenseRef denotes the retained upstream terms without claiming SPDX equivalence; it never '
           'denotes Zog first-party licensing.']}
