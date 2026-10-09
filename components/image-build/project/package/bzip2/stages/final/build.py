# Data only; parsed with ast.literal_eval.
{'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              "cd upstream/bzip2-1.0.8; sed -i 's@\\(ln -s -f \\)$(PREFIX)/bin/@\\1@; "
              "s@(PREFIX)/man@(PREFIX)/share/man@g' Makefile"]],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/bzip2-1.0.8; make -f Makefile-libbz2_so; make clean; make -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/bzip2-1.0.8; make test; printf "Zog bzip2 probe\\n" > probe; ./bzip2 -c '
           'probe | ./bzip2 -dc | cmp - probe']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/bzip2-1.0.8; make PREFIX="$DESTDIR/usr" install; cp -a libbz2.so.* '
              '"$DESTDIR/usr/lib/"; ln -sf libbz2.so.1.0.8 "$DESTDIR/usr/lib/libbz2.so"; ln -sf '
              'libbz2.so.1.0.8 "$DESTDIR/usr/lib/libbz2.so.1"; cp bzip2-shared '
              '"$DESTDIR/usr/bin/bzip2"; ln -sf bzip2 "$DESTDIR/usr/bin/bunzip2"; ln -sf bzip2 '
              '"$DESTDIR/usr/bin/bzcat"']]}
