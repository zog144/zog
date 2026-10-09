# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/e2fsprogs-1.47.4\n'
                'mkdir build\n'
                'cd build\n'
                '../configure --prefix=/usr --sbindir=/usr/sbin --libdir=/usr/lib '
                '--sysconfdir=/etc --enable-elf-shlibs --disable-libblkid --disable-libuuid '
                '--disable-uuidd --disable-fsck']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/e2fsprogs-1.47.4/build\nmake -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/e2fsprogs-1.47.4/build\nmake check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/e2fsprogs-1.47.4/build\n'
              'make DESTDIR="$DESTDIR" install\n'
              'install -d "$DESTDIR/usr/share/licenses/e2fsprogs"\n'
              'install -m644 ../NOTICE "$DESTDIR/usr/share/licenses/e2fsprogs/NOTICE"']]}
