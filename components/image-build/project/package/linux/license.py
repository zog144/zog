# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'linux',
 'version': '7.1.8',
 'source': {'url': 'https://www.kernel.org/pub/linux/kernel/v7.x/linux-7.1.8.tar.xz',
            'sha256': 'ff01dcb449279d5b4cfccdb01fee639cf5ff1803f1749a77844dd33915422c49'},
 'status': 'declared',
 'expression': 'GPL-2.0-only WITH Linux-syscall-note',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'linux-7.1.8/COPYING',
               'sha256': 'fb5a425bd3b3cd6071a3a9aff9909a859e7c1158d54d32e07658398cd67eb6a0',
               'source_sha256': 'ff01dcb449279d5b4cfccdb01fee639cf5ff1803f1749a77844dd33915422c49'},
              {'path': 'linux-7.1.8/LICENSES/exceptions/Linux-syscall-note',
               'sha256': '8e378ab93586eb55135d3bc119cce787f7324f48394777d00c34fa3d0be3303f',
               'source_sha256': 'ff01dcb449279d5b4cfccdb01fee639cf5ff1803f1749a77844dd33915422c49'},
              {'path': 'linux-7.1.8/LICENSES/preferred/GPL-2.0',
               'sha256': '8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa',
               'source_sha256': 'ff01dcb449279d5b4cfccdb01fee639cf5ff1803f1749a77844dd33915422c49'},
              {'path': 'linux-7.1.8/README',
               'sha256': '2844b0b2cafe22741724c4fdda79b1259de48743f12ad40ce408adb1ef00ceda',
               'source_sha256': 'ff01dcb449279d5b4cfccdb01fee639cf5ff1803f1749a77844dd33915422c49'}],
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
