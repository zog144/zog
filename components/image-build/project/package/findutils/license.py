# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'findutils',
 'version': '4.11.0',
 'source': {'url': 'https://ftp.gnu.org/gnu/findutils/findutils-4.11.0.tar.xz',
            'sha256': 'bfd19cb06cc71f3352d567e90284d8cdac02ac89774bbeadf0b533b0c11432fd'},
 'status': 'declared',
 'expression': 'LicenseRef-findutils-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'findutils-4.11.0/COPYING',
               'sha256': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986',
               'source_sha256': 'bfd19cb06cc71f3352d567e90284d8cdac02ac89774bbeadf0b533b0c11432fd'},
              {'path': 'findutils-4.11.0/README',
               'sha256': 'b735d5e5875483854e62a6e4b608155451aa75c39628e40d5b501cd0f464f527',
               'source_sha256': 'bfd19cb06cc71f3352d567e90284d8cdac02ac89774bbeadf0b533b0c11432fd'}],
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
