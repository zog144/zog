# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'grep',
 'version': '3.12',
 'source': {'url': 'https://ftpmirror.gnu.org/grep/grep-3.12.tar.xz',
            'sha256': '2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9'},
 'status': 'declared',
 'expression': 'GPL-3.0-or-later',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'grep-3.12/COPYING',
               'sha256': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986',
               'source_sha256': '2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9'},
              {'path': 'grep-3.12/README',
               'sha256': '82200e18fdbb700ff459ede6ee5f2934638bf8801b0c6272128487fc845d0db2',
               'source_sha256': '2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9'},
              {'path': 'grep-3.12/src/grep.c',
               'sha256': '22ff6b93485baa033ebd3469ded5695d49b5c9aba89dcdb41cc67237a7ad94a0',
               'source_sha256': '2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9'}],
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
