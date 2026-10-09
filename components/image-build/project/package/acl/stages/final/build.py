# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/acl-2.4.0\n'
                './configure --prefix=/usr --libdir=/usr/lib --disable-static']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/acl-2.4.0\nmake -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/acl-2.4.0\n'
           'export PATH=/opt/zog/coreutils-acl-test/bin:$PATH\n'
           '# Exercise the ACL library just built, not the bootstrap fixture library.\n'
           'export LD_LIBRARY_PATH="$PWD/.libs"\n'
           'test "$(command -v cp)" = /opt/zog/coreutils-acl-test/bin/cp\n'
           'test "$(command -v ls)" = /opt/zog/coreutils-acl-test/bin/ls\n'
           'make -j4 check\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/acl-2.4.0\n'
              'make DESTDIR="$DESTDIR" install\n'
              'find "$DESTDIR/usr/lib" -name "*.la" -delete\n'
              'install -Dm644 "doc/COPYING" "$DESTDIR/usr/share/licenses/acl/doc/COPYING"\n'
              'install -Dm644 "doc/COPYING.LGPL" '
              '"$DESTDIR/usr/share/licenses/acl/doc/COPYING.LGPL"']]}
