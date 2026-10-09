# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'flex',
 'version': '2.6.4',
 'source': {'url': 'https://github.com/westes/flex/releases/download/v2.6.4/flex-2.6.4.tar.gz',
            'sha256': 'e87aae032bf07c26f85ac0ed3250998c37621d95f8bd748b31f15b33c45ee995'},
 'status': 'declared',
 'expression': 'LicenseRef-flex-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'flex-2.6.4/COPYING',
               'sha256': '97fd685958d93be7f8dab939bb8161dbd6afb0718c63bfc337c24321aea44273',
               'source_sha256': 'e87aae032bf07c26f85ac0ed3250998c37621d95f8bd748b31f15b33c45ee995'},
              {'path': 'flex-2.6.4/README.md',
               'sha256': '9269b1fe4e79b8504bf9be7d9319ff794f50c6677ee8477a770212ce93134379',
               'source_sha256': 'e87aae032bf07c26f85ac0ed3250998c37621d95f8bd748b31f15b33c45ee995'}],
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
           'denotes Zog first-party licensing.',
           'Retained text contains wording variations; SPDX equivalence is deliberately unresolved '
           'rather than inferred from a license family.']}
