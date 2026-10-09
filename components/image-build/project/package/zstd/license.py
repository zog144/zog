# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'zstd',
 'version': '1.5.7',
 'source': {'url': 'https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz',
            'sha256': 'eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3'},
 'status': 'declared',
 'expression': 'BSD-3-Clause OR GPL-2.0-only',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'zstd-1.5.7/COPYING',
               'sha256': 'f9c375a1be4a41f7b70301dd83c91cb89e41567478859b77eef375a52d782505',
               'source_sha256': 'eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3'},
              {'path': 'zstd-1.5.7/LICENSE',
               'sha256': '7055266497633c9025b777c78eb7235af13922117480ed5c674677adc381c9d8',
               'source_sha256': 'eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3'},
              {'path': 'zstd-1.5.7/README.md',
               'sha256': 'c97c5752f0cf8e235e5834726968708ff1f4b3bf6bfbfcf59db0229b5889ac35',
               'source_sha256': 'eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3'}],
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
