# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/systemd-261.2\n'
                'meson setup build --prefix=/usr --libdir=lib --sysconfdir=/etc '
                '--localstatedir=/var --buildtype=release --wrap-mode=nodownload '
                '--auto-features=disabled -Dmode=release -Dsplit-bin=false -Dtests=true '
                '-Dinstall-tests=false -Dlibmount=enabled -Dblkid=enabled -Dacl=enabled '
                '-Dlibcrypt=enabled -Dkmod=enabled -Dlz4=enabled -Dpcre2=enabled -Dopenssl=enabled '
                '-Dxz=enabled -Dzstd=enabled -Dzlib=enabled -Dnetworkd=true -Dresolve=true '
                '-Dtimesyncd=true -Dsysusers=true -Dtmpfiles=true -Dhwdb=true -Dfirstboot=false '
                '-Dldconfig=false -Drpmmacrosdir=no -Dpamconfdir=no -Ddev-kvm-mode=0660 '
                '-Ddefault-dnssec=no -Ddefault-mdns=no -Ddefault-llmnr=no -Ddns-over-tls=openssl '
                '-Dhomed=disabled -Dlogind=false -Duserdb=false -Dnss-systemd=false '
                '-Dmachined=false -Dportabled=false -Dnspawn=disabled -Dsysext=false '
                '-Dmountfsd=false -Dnsresourced=false -Dvmspawn=disabled -Dsysinstall=false '
                '-Dstoragetm=false -Drepart=disabled -Dsysupdate=disabled -Dimds=disabled '
                '-Dbpf-framework=disabled -Dbootloader=disabled -Dukify=disabled -Dman=disabled '
                '-Dhtml=disabled -Dtranslations=false']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/systemd-261.2\n'
            'meson compile -C build -j8\n'
            '# Meson test dependencies are not default build targets.\n'
            'ninja -C build -j8 test/fuzz/directives.automount test/fuzz/directives.mount '
            'test/fuzz/directives.path test/fuzz/directives.scope test/fuzz/directives.service '
            'test/fuzz/directives.slice test/fuzz/directives.socket test/fuzz/directives.swap '
            'test/fuzz/directives.timer test/fuzz/directives.link test/fuzz/directives.netdev '
            'test/fuzz/directives.network']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/systemd-261.2\n'
           'export LANG=C.UTF-8 LC_ALL=C.UTF-8\n'
           '# Fiber guard probe covers 64 MiB; compilation retains its larger limit.\n'
           'ulimit -S -s 8192\n'
           'meson test -C build --no-rebuild --print-errorlogs -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/systemd-261.2\n'
              'DESTDIR="$DESTDIR" SYSTEMD_OFFLINE=1 meson install -C build --no-rebuild\n'
              'install -d "$DESTDIR/usr/share/licenses/systemd"\n'
              'cp -a LICENSE.GPL2 LICENSE.LGPL2.1 LICENSES '
              '"$DESTDIR/usr/share/licenses/systemd/"']]}
