# Data only; parsed with ast.literal_eval.
{'environment': {'PATH': '/tools/bin:/usr/bin:/bin', 'CONFIG_SITE': '/dev/null'},
 'build': [['/bin/bash',
            '-eu',
            '-c',
            'make -C upstream/linux-7.1.8 mrproper; make -C upstream/linux-7.1.8 ARCH=x86 headers']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'find upstream/linux-7.1.8/usr/include -type f ! -name "*.h" -delete; mkdir -p '
              '"$DESTDIR/sysroot/usr" "$DESTDIR/sysroot/lib64"; cp -r upstream/linux-7.1.8/usr/include '
              '"$DESTDIR/sysroot/usr/"; ln -s usr/lib "$DESTDIR/sysroot/lib"; ln -s '
              '../usr/lib/ld-linux-x86-64.so.2 "$DESTDIR/sysroot/lib64/ld-linux-x86-64.so.2"']]}
