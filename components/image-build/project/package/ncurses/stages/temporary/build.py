# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/image-build/source/host-tools/bin:/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/ncurses-6.6; mkdir native; cd native; ../configure '
              '--prefix=/image-build/source/host-tools AWK=gawk; make -C include; make -C progs '
              'tic -j4; mkdir -p /image-build/source/host-tools/bin; cp progs/tic '
              '/image-build/source/host-tools/bin/tic']],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/ncurses-6.6; ./configure --prefix=/usr --host=x86_64-zog-linux-gnu '
                '--build=x86_64-pc-linux-gnu --mandir=/usr/share/man --with-manpage-format=normal '
                '--with-shared --without-normal --with-cxx-shared --without-debug --without-ada '
                '--disable-stripping AWK=gawk']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/ncurses-6.6; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/ncurses-6.6; make DESTDIR="$DESTDIR/sysroot" install '
              'TIC_PATH=/image-build/source/host-tools/bin/tic; ln -s libncursesw.so '
              '"$DESTDIR/sysroot/usr/lib/libncurses.so"; sed -i "s/^#if.*XOPEN.*$/#if 1/" '
              '"$DESTDIR/sysroot/usr/include/curses.h"; rm -f '
              '"$DESTDIR/sysroot/usr/share/info/dir"; find "$DESTDIR/sysroot/usr/lib" -name "*.la" '
              '-delete 2>/dev/null || test ! -d "$DESTDIR/sysroot/usr/lib"']]}
