# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'gcc',
 'version': '15.3.0',
 'source': {'url': 'https://ftp.gnu.org/gnu/gcc/gcc-15.3.0/gcc-15.3.0.tar.xz',
            'sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
 'status': 'declared',
 'expression': 'GPL-3.0-or-later',
 'scope': 'Primary upstream declaration or retained top-level terms only; see component scopes and '
          'unresolved review notes.',
 'evidence': [{'path': 'gcc-15.3.0/COPYING.RUNTIME',
               'sha256': '9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
              {'path': 'gcc-15.3.0/COPYING3',
               'sha256': '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
              {'path': 'gcc-15.3.0/COPYING.LIB',
               'sha256': 'a9bdde5616ecdd1e980b44f360600ee8783b1f99b8cc83a2beb163a0a390e861',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
              {'path': 'gcc-15.3.0/COPYING3.LIB',
               'sha256': 'a853c2ffec17057872340eee242ae4d96cbf2b520ae27d903e1b2fef1a5f9d1c',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
              {'path': 'gcc-15.3.0/README',
               'sha256': '49306c701a64d02dc25de7c89eac5643a3e73c159b4aa9438b47f6b9d86ba0df',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
              {'path': 'gcc-15.3.0/COPYING',
               'sha256': '231f7edcc7352d7734a96eef0b8030f77982678c516876fcb81e25b32d68564c',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'},
              {'path': 'gcc-15.3.0/libgcc/libgcc2.c',
               'sha256': '00bd4be43efbd9f70f6c8918cfaf7453d5bc1516c469ecb38da8777da4850fcc',
               'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb'}],
 'components': [{'scope': 'Runtime files explicitly carrying the GCC Runtime Library Exception',
                 'expression': 'GPL-3.0-or-later WITH GCC-exception-3.1',
                 'status': 'declared',
                 'notes': 'See libgcc/libgcc2.c and COPYING.RUNTIME; do not apply this exception '
                          'to the compiler executable.'},
                {'scope': 'Other included files, documentation, generated code and bundled '
                          'subprojects',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Complete per-file/stage scope review remains required; primary '
                          'declaration is not a blanket grant.'}],
 'patches': [{'scope': 'patches/strchr-c23.patch and patches/cpython-gcc15.patch; GCC test-suite '
                       'files only',
              'expression': 'GPL-3.0-or-later',
              'status': 'declared',
              'notes': 'Upstream-derived GCC test fixtures retrieved from immutable public Zog source '
                       'commit 8aeb6ad76402a9f91d6408e445190b4c03dd69f8, with GCC 15 API adaptation. '
                       'Preserve GCC COPYING3 and upstream authorship; complete release scope '
                       'review remains pending.'}],
 'notes': ['Inspected exact GCC 15.3.0 release archive on 2026-10-02; stage-specific fallback pin, '
           'no optimizer fix patch.',
           'Declared is not release-reviewed. Per-component notices, exceptions and '
           'corresponding-source obligations require final review.',
           'LicenseRef denotes the retained upstream terms without claiming SPDX equivalence; it '
           'never denotes Zog first-party licensing.',
           'Test-only backports retain GCC upstream terms: strchr upstream 06f094958161; CPython '
           'derived from c2c64cfcd07b and bc615c0d69e, adapted to GCC 15 callback APIs. Patch '
           'files and hashes are declared in sources.py and integration.py and retrieved from immutable '
           'public Zog commit 8aeb6ad76402a9f91d6408e445190b4c03dd69f8. No compiler implementation patch.']}
