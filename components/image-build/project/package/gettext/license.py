# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'gettext',
 'version': '1.0',
 'source': {'url': 'https://ftp.gnu.org/gnu/gettext/gettext-1.0.tar.xz',
            'sha256': '71132a3fb71e68245b8f2ac4e9e97137d3e5c02f415636eb508ae607bc01add7'},
 'status': 'declared',
 'expression': 'LicenseRef-gettext-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'gettext-1.0/COPYING',
               'sha256': 'e79e9c8a0c85d735ff98185918ec94ed7d175efc377012787aebcf3b80f0d90b',
               'source_sha256': '71132a3fb71e68245b8f2ac4e9e97137d3e5c02f415636eb508ae607bc01add7'},
              {'path': 'gettext-1.0/README',
               'sha256': '120ef5af6074554ec79a1aa93804412e55d549c513c56f6521e6b3f36f359517',
               'source_sha256': '71132a3fb71e68245b8f2ac4e9e97137d3e5c02f415636eb508ae607bc01add7'}],
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
