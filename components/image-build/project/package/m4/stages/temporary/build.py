# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/image-build/source/host-tools/bin:/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/m4-1.4.21; ./configure --prefix=/usr --host=x86_64-zog-linux-gnu '
                '--build=x86_64-pc-linux-gnu']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/m4-1.4.21; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/m4-1.4.21; make DESTDIR="$DESTDIR/sysroot" install; rm -f '
              '"$DESTDIR/sysroot/usr/share/info/dir"; find "$DESTDIR/sysroot/usr/lib" -name "*.la" '
              '-delete 2>/dev/null || test ! -d "$DESTDIR/sysroot/usr/lib"']]}
