# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash', '-eu', '-c', 'cd upstream/texinfo-7.3; ./configure --prefix=/usr']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/texinfo-7.3; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/texinfo-7.3; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
