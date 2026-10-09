# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'expect',
 'version': '5.45.4',
 'source': {'url': 'https://prdownloads.sourceforge.net/expect/expect5.45.4.tar.gz',
            'sha256': '49a7da83b0bdd9f46d04a04deec19c7767bb9a323e40c4781f89caf760b92c34'},
 'status': 'declared',
 'expression': 'LicenseRef-expect-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'expect5.45.4/README',
               'sha256': 'b2415b17dc8d9a287f4509047ef5ac3436baef7ba7c50faef5222dcdf61a2bab',
               'source_sha256': '49a7da83b0bdd9f46d04a04deec19c7767bb9a323e40c4781f89caf760b92c34'},
              {'path': 'expect5.45.4/license.terms',
               'sha256': '460e72ef0e4d4796016f46fd5ea9a26f9bdf02e7fb4be356734bb1affd200c44',
               'source_sha256': '49a7da83b0bdd9f46d04a04deec19c7767bb9a323e40c4781f89caf760b92c34'}],
 'components': [{'scope': 'NIST-authored Expect implementation',
                 'expression': 'LicenseRef-expect-upstream-terms',
                 'status': 'declared',
                 'notes': 'license.terms states public domain; this is not a blanket declaration for '
                          'bundled Tcl/build files.'},
                {'scope': 'Other included files, documentation, generated code and bundled subprojects',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Complete per-file/stage scope review remains required; primary declaration '
                          'is not a blanket grant.'}],
 'patches': [{'scope': 'https://www.linuxfromscratch.org/patches/lfs/13.1/expect-5.45.4-gcc15-1.patch',
              'expression': None,
              'status': 'unresolved',
              'notes': 'Source SHA256 ab5fc0af9e2e0f80d7623c1a3a3dbeb1da3d8c9134276792199df401f9eb2cec; '
                       'exact patch provenance retained, licensing review pending.'}],
 'notes': ['Inspected exact release archive on 2026-09-27; source and evidence hashes are bound to this '
           'version.',
           'Declared is not release-reviewed. Per-component notices, exceptions and '
           'corresponding-source obligations require final review.',
           'LicenseRef denotes the retained upstream terms without claiming SPDX equivalence; it never '
           'denotes Zog first-party licensing.']}
