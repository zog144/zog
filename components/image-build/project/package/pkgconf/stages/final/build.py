# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/pkgconf-3.0.5; CFLAGS="-O2 -g -fstack-protector-strong '
                '-D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer" LDFLAGS="-Wl,-z,relro,-z,now" '
                './configure --prefix=/usr --libdir=/usr/lib --disable-static '
                '--with-pkg-config-dir=/usr/lib/pkgconfig:/usr/share/pkgconfig']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/pkgconf-3.0.5; make -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/pkgconf-3.0.5; make -j4 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/pkgconf-3.0.5; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"; ln -s pkgconf "$DESTDIR/usr/bin/pkg-config"']]}
