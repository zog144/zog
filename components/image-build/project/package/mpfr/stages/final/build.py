# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'make -C upstream/mpfr-4.2.2 -j4; make -C upstream/mpfr-4.2.2 html']],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/mpfr-4.2.2; ./configure --prefix=/usr --libdir=/usr/lib '
                '--disable-static --enable-thread-safe --docdir=/usr/share/doc/mpfr-4.2.2']],
 'environment': {'CONFIG_SITE': '/dev/null'},
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/mpfr-4.2.2 DESTDIR="$DESTDIR" install; make -C upstream/mpfr-4.2.2 '
              'DESTDIR="$DESTDIR" install-html']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/mpfr-final; cd '
           'upstream/mpfr-4.2.2; make -j1 check 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/mpfr-final/check.log']]}
