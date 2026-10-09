# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'make -C upstream/mpc-1.4.1 -j4; make -C upstream/mpc-1.4.1 html']],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/mpc-1.4.1; ./configure --prefix=/usr --libdir=/usr/lib '
                '--disable-static --docdir=/usr/share/doc/mpc-1.4.1']],
 'environment': {'CONFIG_SITE': '/dev/null'},
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/mpc-1.4.1 DESTDIR="$DESTDIR" install; make -C upstream/mpc-1.4.1 '
              'DESTDIR="$DESTDIR" install-html']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/mpc-final; cd '
           'upstream/mpc-1.4.1; make -j1 check 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/mpc-final/check.log']]}
