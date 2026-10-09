# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/bison-3.8.2; ./configure --prefix=/usr --docdir=/usr/share/doc/bison-3.8.2']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/bison-3.8.2; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/bison-3.8.2; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
