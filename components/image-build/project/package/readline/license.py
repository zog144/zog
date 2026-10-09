# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'readline',
 'version': '8.3',
 'source': {'url': 'https://ftpmirror.gnu.org/readline/readline-8.3.tar.gz',
            'sha256': 'fe5383204467828cd495ee8d1d3c037a7eba1389c22bc6a041f627976f9061cc'},
 'status': 'declared',
 'expression': 'LicenseRef-readline-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'readline-8.3/COPYING',
               'sha256': '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903',
               'source_sha256': 'fe5383204467828cd495ee8d1d3c037a7eba1389c22bc6a041f627976f9061cc'},
              {'path': 'readline-8.3/README',
               'sha256': 'c66390595e51c1ab99aeac37ee9cd5f7cd652e1ee5da86dea7682f769205e57c',
               'source_sha256': 'fe5383204467828cd495ee8d1d3c037a7eba1389c22bc6a041f627976f9061cc'}],
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
