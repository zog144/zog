# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/attr-2.6.0\n'
                './configure --prefix=/usr --libdir=/usr/lib --disable-static']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/attr-2.6.0\nmake -j8']],
 'test': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/attr-2.6.0\nmake -j4 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/attr-2.6.0\n'
              'make DESTDIR="$DESTDIR" install\n'
              'find "$DESTDIR/usr/lib" -name "*.la" -delete\n'
              'install -Dm644 "doc/COPYING" "$DESTDIR/usr/share/licenses/attr/doc/COPYING"\n'
              'install -Dm644 "doc/COPYING.LGPL" '
              '"$DESTDIR/usr/share/licenses/attr/doc/COPYING.LGPL"']]}
