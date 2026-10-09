# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                "cd upstream/bc-7.0.3; CC='gcc -std=c99' ./configure --prefix=/usr --disable-generated-tests --opt=3 "
                '--enable-internal-history']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C upstream/bc-7.0.3 -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/bc-7.0.3; make test; printf "6*7\\n" | bin/bc | grep -x 42; printf "6 7 * '
           'p\\n" | bin/dc | grep -x 42']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/bc-7.0.3 DESTDIR="$DESTDIR" install']]}
