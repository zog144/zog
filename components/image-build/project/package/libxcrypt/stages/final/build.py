# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/libxcrypt-4.5.2\n'
                './configure --prefix=/usr --libdir=/usr/lib --disable-static '
                '--disable-obsolete-api --enable-hashes=strong,glibc']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/libxcrypt-4.5.2\nmake -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/libxcrypt-4.5.2\nmake -j4 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/libxcrypt-4.5.2\n'
              'make DESTDIR="$DESTDIR" install\n'
              'find "$DESTDIR/usr/lib" -name "*.la" -delete\n'
              'install -Dm644 "COPYING.LIB" "$DESTDIR/usr/share/licenses/libxcrypt/COPYING.LIB"\n'
              'install -Dm644 "LICENSING" "$DESTDIR/usr/share/licenses/libxcrypt/LICENSING"']],
 'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/libxcrypt-4.5.2\n'
              "printf '%s  %s\\n' "
              "'a4bca98dccf0b74a1a3d027faaef7c79209681b6b8908cf6dfd44ff721255dad' "
              "'lib/crypt-gost-yescrypt.c' | sha256sum -c -\n"
              "printf '%s  %s\\n' "
              "'9ceeee7cbcbf757f09237c94388aa18e01532e5ced60aba454bd8b16141c5519' "
              "'lib/crypt-sm3-yescrypt.c' | sha256sum -c -\n"
              "printf '%s  %s\\n' "
              "'f10d86f3155e9c34e9a1d50db0e86ec6aa10a111939642623b421f5998119049' "
              "'../../patches/c23-qualifiers.patch' | sha256sum -c -\n"
              'patch --batch --forward --fuzz=0 -p1 --dry-run < '
              '../../patches/c23-qualifiers.patch\n'
              'patch --batch --forward --fuzz=0 -p1 < ../../patches/c23-qualifiers.patch\n'
              "printf '%s  %s\\n' "
              "'1cf5465bd2393615d2c7fd9f54bc3203b5ddf2d6831f32d1b8cd3651b0d5f62f' "
              "'lib/crypt-gost-yescrypt.c' | sha256sum -c -\n"
              "printf '%s  %s\\n' "
              "'b4a3610b3d6c925ee570f4a1a34a411f7db772bacd3aa2bdf6ad6100f9357763' "
              "'lib/crypt-sm3-yescrypt.c' | sha256sum -c -\n"]]}
