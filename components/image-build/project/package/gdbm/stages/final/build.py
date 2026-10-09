# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/gdbm-1.26; CFLAGS="-O2 -g -fstack-protector-strong '
                '-D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer" LDFLAGS="-Wl,-z,relro,-z,now" '
                './configure --prefix=/usr --libdir=/usr/lib --disable-static '
                '--enable-libgdbm-compat --without-readline']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/gdbm-1.26; make -j8']],
 'test': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/gdbm-1.26; make -j4 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/gdbm-1.26; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
