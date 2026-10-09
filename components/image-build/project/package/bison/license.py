# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'bison',
 'version': '3.8.2',
 'source': {'url': 'https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz',
            'sha256': '9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2'},
 'status': 'declared',
 'expression': 'GPL-3.0-or-later',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'bison-3.8.2/README',
               'sha256': '19a802ad381694b73268cde2453f6ee8d6d7ca4eed72bc515be3c4255c022f4d',
               'source_sha256': '9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2'},
              {'path': 'bison-3.8.2/COPYING',
               'sha256': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986',
               'source_sha256': '9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2'},
              {'path': 'bison-3.8.2/src/main.c',
               'sha256': 'f9059707d20e0f115192b6bf1ebd6bae8c19c0c1c6a5b5a9ea2cf67653555a94',
               'source_sha256': '9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2'},
              {'path': 'bison-3.8.2/data/skeletons/yacc.c',
               'sha256': '998d3a462761d5e6b9c408b6744b8741dc5b59eb7df47e9057055de45ee799df',
               'source_sha256': '9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2'}],
 'components': [{'scope': 'Generated parsers from exception-bearing skeletons',
                 'expression': 'GPL-3.0-or-later WITH Bison-exception-2.2',
                 'status': 'unresolved',
                 'notes': 'Review the installed skeleton and its exception text; this does not change '
                          'the license of the Bison executable.'},
                {'scope': 'Other included files, documentation, generated code and bundled subprojects',
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
