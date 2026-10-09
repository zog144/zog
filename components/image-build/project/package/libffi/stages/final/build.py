# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/libffi-3.8.0; CFLAGS="-O2 -g -fstack-protector-strong '
                '-D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer" LDFLAGS="-Wl,-z,relro,-z,now" '
                './configure --prefix=/usr --libdir=/usr/lib --disable-static --without-gcc-arch '
                '--disable-multi-os-directory']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/libffi-3.8.0; make -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/libffi-3.8.0; make -j4 check; test -s */testsuite/libffi.sum; if grep -E '
           "'^(FAIL|XPASS|ERROR|UNRESOLVED):' */testsuite/libffi.sum; then exit 1; fi"]],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/libffi-3.8.0; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
