# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/image-build/source/host-tools/bin:/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes',
                 'bash_cv_getcwd_malloc': 'yes'},
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/bash-5.3; ./configure --prefix=/usr --host=x86_64-zog-linux-gnu '
                '--build=x86_64-pc-linux-gnu --without-bash-malloc']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/bash-5.3; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/bash-5.3; make DESTDIR="$DESTDIR/sysroot" install; ln -s bash '
              '"$DESTDIR/sysroot/usr/bin/sh"; rm -f "$DESTDIR/sysroot/usr/share/info/dir"; find '
              '"$DESTDIR/sysroot/usr/lib" -name "*.la" -delete 2>/dev/null || test ! -d '
              '"$DESTDIR/sysroot/usr/lib"']],
 'test': [['/bin/bash',
           '-eu',
           '-c',
           'env -u PWD /sysroot/usr/lib/ld-linux-x86-64.so.2 --library-path /sysroot/usr/lib '
           '/image-build/source/upstream/bash-5.3/bash -eu -c \'test "$(pwd -P)" = '
           '/image-build/source; test "$(/usr/bin/pwd -P)" = /image-build/source; (cd /; test '
           '"$(pwd -P)" = /); printf "Bash working-directory acceptance passed\\n"\'']]}
