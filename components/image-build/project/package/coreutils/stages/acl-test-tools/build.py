# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/coreutils-9.11\n'
                'CPPFLAGS=-I/opt/zog/acl-test-bootstrap/include '
                'LDFLAGS=-L/opt/zog/acl-test-bootstrap/lib '
                'LD_LIBRARY_PATH=/opt/zog/acl-test-bootstrap/lib ./configure '
                '--prefix=/opt/zog/coreutils-acl-test --enable-acl --disable-libcap --without-gmp\n'
                '# --enable-acl must not silently degrade if detection fails.\n'
                "grep -Eq '^#define USE_ACL 1$' lib/config.h\n"]],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/coreutils-9.11\nmake -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/coreutils-9.11\n'
           'export LD_LIBRARY_PATH=/opt/zog/acl-test-bootstrap/lib\n'
           'src/cp --version\n'
           'src/ls --version\n'
           '# Behavioural acceptance is the complete unchanged ACL suite in acl-final.\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/coreutils-9.11\n'
              'install -Dm755 src/cp "$DESTDIR/opt/zog/coreutils-acl-test/bin/cp"\n'
              'install -Dm755 src/ls "$DESTDIR/opt/zog/coreutils-acl-test/bin/ls"\n'
              'install -Dm644 COPYING '
              '"$DESTDIR/opt/zog/coreutils-acl-test/share/licenses/coreutils/COPYING"\n']],
 'environment': {'LD_LIBRARY_PATH': '/opt/zog/acl-test-bootstrap/lib'}}
