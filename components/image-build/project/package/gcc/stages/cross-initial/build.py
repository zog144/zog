# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/tools/bin:/usr/bin:/bin', 'CONFIG_SITE': '/dev/null'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              'mv gmp-source/gmp-6.3.0 upstream/gcc-16.2.0/gmp; mv mpfr-source/mpfr-4.2.2 '
              'upstream/gcc-16.2.0/mpfr; mv mpc-source/mpc-1.4.1 upstream/gcc-16.2.0/mpc; sed -i.orig '
              '"/m64=/s/lib64/lib/" upstream/gcc-16.2.0/gcc/config/i386/t-linux64']],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; ../upstream/gcc-16.2.0/configure --target=x86_64-zog-linux-gnu '
                '--prefix=/tools --with-glibc-version=2.44 --with-sysroot=/sysroot --with-newlib '
                '--without-headers --enable-default-pie --enable-default-ssp --disable-fixincludes '
                '--disable-nls --disable-shared --disable-multilib --disable-threads --disable-libatomic '
                '--disable-libgomp --disable-libquadmath --disable-libssp --disable-libvtv '
                '--disable-libstdcxx --enable-languages=c,c++']],
 'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'make -C build DESTDIR="$DESTDIR" install; cat '
              'upstream/gcc-16.2.0/gcc/{limitx,glimits,limity}.h > '
              '"$DESTDIR/tools/lib/gcc/x86_64-zog-linux-gnu/16.2.0/include/limits.h"; rm -f '
              '"$DESTDIR/tools/share/info/dir"']]}
