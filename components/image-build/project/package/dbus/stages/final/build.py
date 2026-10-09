# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/dbus-1.16.2\n'
                'meson setup build --prefix=/usr --libdir=lib --sysconfdir=/etc '
                '--localstatedir=/var --buildtype=release --wrap-mode=nodownload -Dsystemd=enabled '
                '-Dsystemd_system_unitdir=/usr/lib/systemd/system '
                '-Dsystemd_user_unitdir=/usr/lib/systemd/user -Druntime_dir=/run '
                '-Ddbus_user=messagebus -Dapparmor=disabled -Dselinux=disabled -Dlibaudit=disabled '
                '-Ddoxygen_docs=disabled -Dducktype_docs=disabled -Dqt_help=disabled '
                '-Dxml_docs=disabled -Dx11_autolaunch=disabled']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/dbus-1.16.2\nmeson compile -C build -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/dbus-1.16.2\nmeson test -C build --no-rebuild --print-errorlogs -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/dbus-1.16.2\n'
              'DESTDIR="$DESTDIR" meson install -C build --no-rebuild\n'
              'install -d "$DESTDIR/usr/share/licenses/dbus"\n'
              'cp -a COPYING LICENSES "$DESTDIR/usr/share/licenses/dbus/"\n'
              '# Machine identity and account creation belong to host-install.\n'
              'test ! -e "$DESTDIR/var/lib/dbus/machine-id"']]}
