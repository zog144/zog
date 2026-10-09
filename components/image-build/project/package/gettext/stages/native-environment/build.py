# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/gettext-1.0; ./configure --prefix=/usr --disable-shared']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/gettext-1.0; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/gettext-1.0; mkdir -p "$DESTDIR/usr/bin"; cp gettext-tools/src/msgfmt '
              'gettext-tools/src/msgmerge gettext-tools/src/xgettext "$DESTDIR/usr/bin/"']]}
