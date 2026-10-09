# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/gperf-3.3; ./configure --prefix=/usr']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C upstream/gperf-3.3 -j8']],
 'test': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C upstream/gperf-3.3 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/gperf-3.3 DESTDIR="$DESTDIR" install\n'
              'rm -f "$DESTDIR/usr/share/info/dir"\n'
              'install -Dm644 upstream/gperf-3.3/COPYING '
              '"$DESTDIR/usr/share/licenses/gperf/COPYING"']]}
