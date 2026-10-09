# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/mpdecimal-4.0.1; ./configure --prefix=/usr --disable-static '
                '--docdir=/usr/share/doc/mpdecimal-4.0.1']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/mpdecimal-4.0.1; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/mpdecimal-4.0.1; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
