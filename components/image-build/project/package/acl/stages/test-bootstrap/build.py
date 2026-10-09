# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/acl-2.4.0\n'
                './configure --prefix=/opt/zog/acl-test-bootstrap '
                '--libdir=/opt/zog/acl-test-bootstrap/lib --disable-static']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/acl-2.4.0\nmake -j8']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/acl-2.4.0\n'
              'make DESTDIR="$DESTDIR" install\n'
              'find "$DESTDIR/opt" -name "*.la" -delete']]}
