# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/tools/bin:/usr/bin:/bin', 'CONFIG_SITE': '/dev/null'},
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; ../upstream/binutils-2.47/configure --prefix=/tools '
                '--with-sysroot=/sysroot --target=x86_64-zog-linux-gnu --disable-nls --enable-gprofng=no '
                '--disable-werror --enable-new-dtags --enable-default-hash-style=gnu']],
 'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'make -C build DESTDIR="$DESTDIR" install; rm -f "$DESTDIR/tools/share/info/dir"']]}
