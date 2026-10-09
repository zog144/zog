# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              'mv gmp-source/gmp-6.3.0 upstream/gcc-16.2.0/gmp; mv mpfr-source/mpfr-4.2.2 '
              'upstream/gcc-16.2.0/mpfr; mv mpc-source/mpc-1.4.1 upstream/gcc-16.2.0/mpc; sed '
              '-i.orig "/m64=/s/lib64/lib/" upstream/gcc-16.2.0/gcc/config/i386/t-linux64']],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; ../upstream/gcc-16.2.0/configure '
                '--build=x86_64-pc-linux-gnu --host=x86_64-zog-linux-gnu '
                '--target=x86_64-zog-linux-gnu --prefix=/usr --with-build-sysroot=/sysroot '
                '--enable-default-pie --enable-default-ssp --disable-fixincludes --disable-nls '
                '--disable-multilib --disable-libatomic --disable-libgomp --disable-libquadmath '
                '--disable-libsanitizer --disable-libssp --disable-libvtv --enable-languages=c,c++ '
                'CXX_FOR_TARGET="x86_64-zog-linux-gnu-gcc -nostdinc++" '
                'LDFLAGS_FOR_TARGET="-L$PWD/x86_64-zog-linux-gnu/libgcc" '
                'target_configargs=gcc_cv_target_thread_file=posix']],
 'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'make -C build DESTDIR="$DESTDIR/sysroot" install; ln -s gcc '
              '"$DESTDIR/sysroot/usr/bin/cc"; rm -f "$DESTDIR/sysroot/usr/share/info/dir"; find '
              '"$DESTDIR/sysroot/usr/lib" -name "*.la" -delete']]}
