# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/image-build/source/host-tools/bin:/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; ../upstream/gcc-16.2.0/libstdc++-v3/configure '
                '--host=x86_64-zog-linux-gnu --build=x86_64-pc-linux-gnu '
                'CXX=x86_64-zog-linux-gnu-gcc --prefix=/usr --disable-multilib --disable-nls '
                '--disable-libstdcxx-pch '
                '--with-gxx-include-dir=/tools/x86_64-zog-linux-gnu/include/c++/16.2.0']],
 'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'make -C build DESTDIR="$DESTDIR/sysroot" install; rm -f '
              '"$DESTDIR/sysroot/usr/share/info/dir"; find "$DESTDIR/sysroot/usr/lib" -name "*.la" '
              '-delete 2>/dev/null || test ! -d "$DESTDIR/sysroot/usr/lib"']]}
