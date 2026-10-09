# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/util-linux-2.42.2\n'
                './configure --prefix=/usr --bindir=/usr/bin --sbindir=/usr/sbin --libdir=/usr/lib '
                '--disable-all-programs --enable-nologin --disable-pylibmount --disable-static '
                '--disable-liblastlog2 --without-python --disable-makeinstall-chown '
                '--disable-makeinstall-setuid']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/util-linux-2.42.2\nmake -j8 nologin']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/util-linux-2.42.2\n'
           'rc=0\n'
           './nologin -c "touch /tmp/zog-nologin-command-must-not-run" || rc=$?\n'
           'test "$rc" -eq 1\n'
           'test ! -e /tmp/zog-nologin-command-must-not-run']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/util-linux-2.42.2\n'
              'install -Dm755 nologin "$DESTDIR/usr/sbin/nologin"\n'
              'install -d "$DESTDIR/usr/share/licenses/util-linux-nologin"\n'
              'cp -a COPYING README.licensing Documentation/licenses '
              '"$DESTDIR/usr/share/licenses/util-linux-nologin/"']]}
