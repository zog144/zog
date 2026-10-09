# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/tools/bin:/usr/bin:/bin', 'CONFIG_SITE': '/dev/null'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/glibc-2.44; patch -Np1 -i ../../patches/fhs.patch; patch -Np1 -i '
              '../../patches/upstream.patch']],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; echo rootsbindir=/usr/sbin > configparms; '
                '../upstream/glibc-2.44/configure --prefix=/usr --host=x86_64-zog-linux-gnu '
                '--build=$(../upstream/glibc-2.44/scripts/config.guess) --with-headers=/sysroot/usr/include '
                '--disable-nscd libc_cv_slibdir=/usr/lib --enable-kernel=5.10']],
 'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'make -C build DESTDIR="$DESTDIR/sysroot" install; sed "/RTLDLIST=/s@/usr@@g" -i '
              '"$DESTDIR/sysroot/usr/bin/ldd"']]}
