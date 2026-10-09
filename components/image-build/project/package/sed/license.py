# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'sed',
 'version': '4.10',
 'source': {'url': 'https://ftpmirror.gnu.org/sed/sed-4.10.tar.xz',
            'sha256': 'b8e72182b2ec96a3574e2998c47b7aaa64cc20ce000d8e9ac313cc07cecf28c7'},
 'status': 'declared',
 'expression': 'GPL-3.0-or-later',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'sed-4.10/COPYING',
               'sha256': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986',
               'source_sha256': 'b8e72182b2ec96a3574e2998c47b7aaa64cc20ce000d8e9ac313cc07cecf28c7'},
              {'path': 'sed-4.10/README',
               'sha256': 'd5b811607f01454e012c37e1548f97ce53a0d895f2b51a9332646dae13ef9829',
               'source_sha256': 'b8e72182b2ec96a3574e2998c47b7aaa64cc20ce000d8e9ac313cc07cecf28c7'},
              {'path': 'sed-4.10/sed/sed.c',
               'sha256': '800c10186e55d7475bd57459ef6577c1e8261352599fbe81126c23bf906a8ace',
               'source_sha256': 'b8e72182b2ec96a3574e2998c47b7aaa64cc20ce000d8e9ac313cc07cecf28c7'}],
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
