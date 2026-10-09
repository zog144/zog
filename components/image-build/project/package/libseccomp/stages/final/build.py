# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/libseccomp-2.6.0\n'
                './configure --prefix=/usr --libdir=/usr/lib --disable-static']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/libseccomp-2.6.0\nmake -j8']],
 'test': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/libseccomp-2.6.0\nmake check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/libseccomp-2.6.0\n'
              'make DESTDIR="$DESTDIR" install\n'
              'install -d "$DESTDIR/usr/share/licenses/libseccomp"\n'
              'install -m644 LICENSE "$DESTDIR/usr/share/licenses/libseccomp/LICENSE"']]}
