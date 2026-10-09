# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/image-build/source/host-tools/bin:/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/file-5.48; mkdir native; cd native; ../configure --disable-bzlib '
              '--disable-libseccomp --disable-xzlib --disable-zlib; make -j4']],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/file-5.48; ./configure --prefix=/usr --host=x86_64-zog-linux-gnu '
                '--build=x86_64-pc-linux-gnu --disable-bzlib --disable-libseccomp --disable-xzlib '
                '--disable-zlib']],
 'build': [['/bin/bash',
            '-eu',
            '-c',
            'cd upstream/file-5.48; make -j4 '
            'FILE_COMPILE=/image-build/source/upstream/file-5.48/native/src/file']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/file-5.48; make DESTDIR="$DESTDIR/sysroot" install '
              'FILE_COMPILE=/image-build/source/upstream/file-5.48/native/src/file; rm -f '
              '"$DESTDIR/sysroot/usr/share/info/dir"; find "$DESTDIR/sysroot/usr/lib" -name "*.la" '
              '-delete 2>/dev/null || test ! -d "$DESTDIR/sysroot/usr/lib"']]}
