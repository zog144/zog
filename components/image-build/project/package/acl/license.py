# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'acl',
 'version': '2.4.0',
 'source': {'url': 'https://download.savannah.gnu.org/releases/acl/acl-2.4.0.tar.xz',
            'sha256': 'e661131456d2708a01c614a0f400e11d7d1bfaeb6f3e74b75bb980b72f0161a3'},
 'status': 'declared',
 'expression': 'GPL-2.0-or-later AND LGPL-2.1-or-later',
 'scope': 'Primary project/library/tool terms; component detail remains subject to release review.',
 'evidence': [{'path': 'acl-2.4.0/doc/COPYING',
               'sha256': 'a45a845012742796534f7e91fe623262ccfb99460a2bd04015bd28d66fba95b8',
               'source_sha256': 'e661131456d2708a01c614a0f400e11d7d1bfaeb6f3e74b75bb980b72f0161a3'},
              {'path': 'acl-2.4.0/doc/COPYING.LGPL',
               'sha256': '01b1f9f2c8ee648a7a596a1abe8aa4ed7899b1c9e5551bda06da6e422b04aa55',
               'source_sha256': 'e661131456d2708a01c614a0f400e11d7d1bfaeb6f3e74b75bb980b72f0161a3'}],
 'components': [{'scope': 'Auxiliary files, bundled tests and licensing exceptions',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Retained archive and source notices; complete per-file review pending. '
                          'libxcrypt LICENSING enumerates additional terms; PCRE2 terms retained '
                          'without blanket SPDX simplification.'}],
 'patches': [],
 'notes': ['No source patch; exact release archive and notices inspected 2026-10-07.']}
