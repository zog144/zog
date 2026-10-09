# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/lz4-1.10.0\nmake -j8 PREFIX=/usr libdir=/usr/lib BUILD_STATIC=no']],
 'test': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/lz4-1.10.0\nmake -j4 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/lz4-1.10.0\n'
              'make PREFIX=/usr libdir=/usr/lib BUILD_STATIC=no DESTDIR="$DESTDIR" install\n'
              'install -Dm644 "LICENSE" "$DESTDIR/usr/share/licenses/lz4/LICENSE"\n'
              'install -Dm644 "lib/LICENSE" "$DESTDIR/usr/share/licenses/lz4/lib/LICENSE"\n'
              'install -Dm644 "programs/COPYING" '
              '"$DESTDIR/usr/share/licenses/lz4/programs/COPYING"']]}
