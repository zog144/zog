# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'ncurses',
 'version': '6.6',
 'source': {'url': 'https://invisible-mirror.net/archives/ncurses/ncurses-6.6.tar.gz',
            'sha256': '355b4cbbed880b0381a04c46617b7656e362585d52e9cf84a67e2009b749ff11'},
 'status': 'declared',
 'expression': 'LicenseRef-ncurses-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'ncurses-6.6/COPYING',
               'sha256': '708999f95527e1ffa670c6fce288c6c600cb477dd04afcc1171422b3dd4ee226',
               'source_sha256': '355b4cbbed880b0381a04c46617b7656e362585d52e9cf84a67e2009b749ff11'},
              {'path': 'ncurses-6.6/README',
               'sha256': '1b79c236eae9b7d16d25c7895d206f0c488fba01b3ee8968e68975d8749163c1',
               'source_sha256': '355b4cbbed880b0381a04c46617b7656e362585d52e9cf84a67e2009b749ff11'}],
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
