# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/image-build/source/host-tools/bin:/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/coreutils-9.11; ./configure --prefix=/usr --host=x86_64-zog-linux-gnu '
                '--build=x86_64-pc-linux-gnu --enable-install-program=hostname']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/coreutils-9.11; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/coreutils-9.11; make DESTDIR="$DESTDIR/sysroot" install; mkdir -p '
              '"$DESTDIR/sysroot/usr/sbin" "$DESTDIR/sysroot/usr/share/man/man8"; mv '
              '"$DESTDIR/sysroot/usr/bin/chroot" "$DESTDIR/sysroot/usr/sbin/"; mv '
              '"$DESTDIR/sysroot/usr/share/man/man1/chroot.1" '
              '"$DESTDIR/sysroot/usr/share/man/man8/chroot.8"; sed -i \'s/"1"/"8"/\' '
              '"$DESTDIR/sysroot/usr/share/man/man8/chroot.8"; rm -f '
              '"$DESTDIR/sysroot/usr/share/info/dir"; find "$DESTDIR/sysroot/usr/lib" -name "*.la" '
              '-delete 2>/dev/null || test ! -d "$DESTDIR/sysroot/usr/lib"']]}
