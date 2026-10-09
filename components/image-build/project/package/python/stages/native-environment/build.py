# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/Python-3.14.7; ./configure --prefix=/usr --enable-shared --without-ensurepip '
                '--without-static-libpython']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/Python-3.14.7; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/Python-3.14.7; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
