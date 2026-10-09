# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/kmod-34.2\n'
                'meson setup build --prefix=/usr --libdir=lib --buildtype=release '
                '--wrap-mode=nodownload -Dmanpages=false -Ddocs=false -Dbuild-tests=false '
                '-Dzstd=enabled -Dxz=enabled -Dzlib=enabled -Dopenssl=enabled']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/kmod-34.2\nmeson compile -C build -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/kmod-34.2\nbuild/kmod --version']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/kmod-34.2\n'
              'DESTDIR="$DESTDIR" meson install -C build --no-rebuild\n'
              'install -Dm644 "COPYING" "$DESTDIR/usr/share/licenses/kmod/COPYING"']]}
