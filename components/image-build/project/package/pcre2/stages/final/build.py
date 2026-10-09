# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/pcre2-10.47\n'
                'cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_INSTALL_LIBDIR=lib '
                '-DBUILD_SHARED_LIBS=ON -DPCRE2_BUILD_PCRE2_8=ON -DPCRE2_BUILD_PCRE2_16=ON '
                '-DPCRE2_BUILD_PCRE2_32=ON -DPCRE2_SUPPORT_JIT=ON -DPCRE2_BUILD_TESTS=ON '
                '-DCMAKE_BUILD_TYPE=Release']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/pcre2-10.47\ncmake --build build -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/pcre2-10.47\nctest --test-dir build --output-on-failure -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/pcre2-10.47\n'
              'DESTDIR="$DESTDIR" cmake --install build\n'
              'install -Dm644 "LICENCE.md" "$DESTDIR/usr/share/licenses/pcre2/LICENCE.md"']]}
