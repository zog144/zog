# Upstream licensing data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'util-linux',
 'version': '2.42.2',
 'source': {'url': 'https://www.kernel.org/pub/linux/utils/util-linux/v2.42/util-linux-2.42.2.tar.xz',
            'sha256': '03a05d3adf9602ef128f2da05b84b3205ce60c351e5737c0370f74000679ce8a'},
 'status': 'declared',
 'expression': 'LicenseRef-util-linux-upstream-terms',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'util-linux-2.42.2/COPYING',
               'sha256': '8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643',
               'source_sha256': '03a05d3adf9602ef128f2da05b84b3205ce60c351e5737c0370f74000679ce8a'},
              {'path': 'util-linux-2.42.2/README',
               'sha256': 'c79f1c65037a983486006f06fe1f6a4869d01b46b160d8efd447c49a64826749',
               'source_sha256': '03a05d3adf9602ef128f2da05b84b3205ce60c351e5737c0370f74000679ce8a'},
              {'path': 'util-linux-2.42.2/README.licensing',
               'sha256': '4c2db318192bda62f3f8fcf71488bb5e602ae4385eba281d711b46cc13a40bb3',
               'source_sha256': '03a05d3adf9602ef128f2da05b84b3205ce60c351e5737c0370f74000679ce8a'}],
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
