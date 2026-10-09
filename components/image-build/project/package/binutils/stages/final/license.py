# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'binutils',
 'version': '2.47',
 'source': {'url': 'https://sourceware.org/pub/binutils/releases/binutils-2.47.tar.xz',
            'sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
 'status': 'declared',
 'expression': 'GPL-3.0-or-later',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'binutils-2.47/COPYING',
               'sha256': '231f7edcc7352d7734a96eef0b8030f77982678c516876fcb81e25b32d68564c',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
              {'path': 'binutils-2.47/COPYING.LIB',
               'sha256': '56bdea73b6145ef6ac5259b3da390b981d840c24cb03b8e1cbc678de7ecfa18d',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
              {'path': 'binutils-2.47/COPYING3',
               'sha256': '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
              {'path': 'binutils-2.47/COPYING3.LIB',
               'sha256': 'a853c2ffec17057872340eee242ae4d96cbf2b520ae27d903e1b2fef1a5f9d1c',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
              {'path': 'binutils-2.47/README',
               'sha256': 'dfd8ec4586c3c2cb55234793b0b955e600ae8e708f13b6be143768273c57c9e7',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
              {'path': 'binutils-2.47/binutils/objcopy.c',
               'sha256': '541461c87c1bc8ea5f16893b92e26a424016a03354e441671bfdc9d7fdc8b28c',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'},
              {'path': 'binutils-2.47/gprofng/src/gp-gmon.cc',
               'sha256': '490f1e5673dd349a1269f7317923ffb8617354a34bc8a545f79718bc3ae9bc9b',
               'source_sha256': '154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff'}],
 'components': [{'scope': 'Other included files, documentation, generated code and bundled '
                          'subprojects',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Complete per-file/stage scope review remains required; primary '
                          'declaration is not a blanket grant.'}],
 'patches': [{'scope': 'Final stage only: gprofng-34502, source SHA256 '
                       'cc4aaa5749b3b6cb3d5296ec1485c667c8e438dbd32b1530025e19cf95896060',
              'expression': 'GPL-3.0-or-later',
              'status': 'declared',
              'notes': 'Upstream commit 2d570d754422b4990f590829c4bed905a327bc7b by H.J. Lu '
                       'modifies gprofng/src/gp-gmon.cc, whose retained header states GPL version '
                       '3 or later. Patch identity and application hashes are in integration.py; '
                       'complete release review remains outstanding.'}],
 'notes': ['Inspected exact release archive on 2026-09-27; source and evidence hashes are bound to '
           'this version.',
           'Declared is not release-reviewed. Per-component notices, exceptions and '
           'corresponding-source obligations require final review.',
           'LicenseRef denotes the retained upstream terms without claiming SPDX equivalence; it '
           'never denotes Zog first-party licensing.']}
