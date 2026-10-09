# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/iproute2-7.1.0\n./configure --libbpf_force=off']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/iproute2-7.1.0\n'
            'make -j8 PREFIX=/usr SBINDIR=/usr/sbin NETNS_RUN_DIR=/run/netns']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/iproute2-7.1.0\n./ip/ip -Version\n./misc/ss -Version\n./tc/tc -Version']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/iproute2-7.1.0\n'
              'make DESTDIR="$DESTDIR" PREFIX=/usr SBINDIR=/usr/sbin NETNS_RUN_DIR=/run/netns '
              'install\n'
              'install -d "$DESTDIR/usr/share/licenses/iproute2"\n'
              'install -m644 COPYING "$DESTDIR/usr/share/licenses/iproute2/COPYING"']]}
