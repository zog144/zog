# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/tools/bin:/usr/bin:/bin',
                 'CONFIG_SITE': '/dev/null',
                 'ac_cv_func_posix_spawn_file_actions_addchdir': 'yes',
                 'ac_cv_func_posix_spawn_file_actions_addfchdir': 'yes'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              "sed '6031s/$add_dir//' -i upstream/binutils-2.47/ltmain.sh"]],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; ../upstream/binutils-2.47/configure --prefix=/usr '
                '--build=x86_64-pc-linux-gnu --host=x86_64-zog-linux-gnu --disable-nls '
                '--enable-shared --enable-gprofng=no --disable-werror --enable-64-bit-bfd '
                '--enable-new-dtags --enable-default-hash-style=gnu']],
 'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'make -C build DESTDIR="$DESTDIR/sysroot" install; rm -f '
              '"$DESTDIR/sysroot/usr/share/info/dir"; rm -f '
              '"$DESTDIR"/sysroot/usr/lib/lib{bfd,ctf,ctf-nobfd,opcodes,sframe}.{a,la}']]}
