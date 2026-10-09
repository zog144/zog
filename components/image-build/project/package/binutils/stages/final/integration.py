# Data only; parsed with ast.literal_eval.
{'project': 'binutils',
 'stage_id': 'final',
 'version': '2.47',
 'reference': 'https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter08/binutils.html',
 'test_policy': 'Mandatory upstream tests. Unexpected results stop the graph; no automatic '
                'known-failure waiver.',
 'bootstrap_contract': 'Verified source-built final-libc root. Compiler replacements require '
                       'recorded old-file ownership.',
 'patches': [{'id': 'gprofng-34502',
              'origin': 'upstream',
              'commit': '2d570d754422b4990f590829c4bed905a327bc7b',
              'bug': 'https://sourceware.org/bugzilla/show_bug.cgi?id=34502',
              'author': 'H.J. Lu',
              'source': {'url': 'https://sourceware.org/git/?p=binutils-gdb.git;a=patch;h=2d570d754422b4990f590829c4bed905a327bc7b',
                         'sha256': 'cc4aaa5749b3b6cb3d5296ec1485c667c8e438dbd32b1530025e19cf95896060',
                         'destination': 'patches/gprofng-34502.patch',
                         'archive': False},
              'applies_to': {'version': '2.47', 'stage': 'final'},
              'reason': 'Correct the executable file offset in gmon conversion so calltree symbols '
                        'resolve.',
              'order': 1,
              'strip': 1,
              'fuzz': 0,
              'files': [{'path': 'gprofng/src/gp-gmon.cc',
                         'before_sha256': '490f1e5673dd349a1269f7317923ffb8617354a34bc8a545f79718bc3ae9bc9b',
                         'after_sha256': 'b95236fb781bb659adaf9c278a37edc08b0922ff583ff47c16b8cda121e6246a'}],
              'review': 'Reviewed upstream diff; live corrected-map probes pass. Full patched '
                        'build acceptance pending.',
              'retirement': 'On a Binutils version update, check for upstream commit inclusion and '
                            'remove this backport only with equivalent passing tests.'}]}
