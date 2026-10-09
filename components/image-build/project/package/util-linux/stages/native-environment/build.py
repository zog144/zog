# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/util-linux-2.42.2; ./configure --prefix=/usr --bindir=/usr/bin '
                '--sbindir=/usr/sbin --libdir=/usr/lib --runstatedir=/run --disable-chfn-chsh '
                '--disable-login --disable-nologin --disable-su --disable-setpriv --disable-runuser '
                '--disable-pylibmount --disable-static --disable-liblastlog2 --without-python '
                '--disable-makeinstall-chown --disable-makeinstall-setuid '
                'ADJTIME_PATH=/var/lib/hwclock/adjtime --docdir=/usr/share/doc/util-linux-2.42.2']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/util-linux-2.42.2; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/util-linux-2.42.2; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"; mkdir -p "$DESTDIR/var/lib/hwclock"']]}
