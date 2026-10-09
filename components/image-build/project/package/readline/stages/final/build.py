# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/readline-8.3; CFLAGS="-O2 -g '
                '-fstack-protector-strong -D_FORTIFY_SOURCE=3" '
                'LDFLAGS="-Wl,-z,relro,-z,now" ./configure --prefix=/usr '
                '--libdir=/usr/lib --with-curses --disable-static']],
 'build': [['/bin/bash',
            '-eu',
            '-c',
            'cd upstream/readline-8.3; make -j8 SHLIB_LIBS=-lncursesw']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/readline-8.3; make DESTDIR="$DESTDIR" '
              'SHLIB_LIBS=-lncursesw install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
