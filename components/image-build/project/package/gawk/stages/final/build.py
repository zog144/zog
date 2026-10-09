# Data only; parsed with ast.literal_eval.
{'environment': {'CONFIG_SITE': '/dev/null'},
 'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              "cd upstream/gawk-5.4.1; sed -i 's/extras//' Makefile.in"]],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/gawk-5.4.1; ./configure --prefix=/usr --without-readline; grep -Eq '
                '"^#define HAVE_MPFR 1$" config.h']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/gawk-5.4.1; make -j4']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/gawk-5.4.1; test "$(./gawk \'BEGIN { if (a["x"] == "") n++; a["x"] = '
           'a["x"] "Wabsolute-value"; print a["x"] }\')" = Wabsolute-value\n'
           './gawk -M -v PREC=128 \'BEGIN { if (!("mpfr_version" in PROCINFO)) exit 1; print '
           '"MPFR", PROCINFO["mpfr_version"]; if (2^100 + 1 == 2^100) exit 1 }\'\n'
           'mkdir -p /image-build/source/test-locales\n'
           'for locale_name in en_US fr_FR ru_RU ja_JP; do\n'
           '  localedef --no-archive -i "$locale_name" -f UTF-8 '
           '"/image-build/source/test-locales/$locale_name.UTF-8"\n'
           'done\n'
           'localedef --no-archive -i el_GR -f ISO-8859-7 '
           '/image-build/source/test-locales/el_GR.iso88597@euro\n'
           'export LOCPATH=/image-build/source/test-locales\n'
           "python3 - <<'VERIFY_LOCALES'\n"
           'import locale\n'
           "for name in ['en_US.UTF-8', 'fr_FR.UTF-8', 'ru_RU.UTF-8', 'ja_JP.UTF-8', "
           "'el_GR.iso88597@euro']:\n"
           '    locale.setlocale(locale.LC_ALL, name)\n'
           "    print('Verified Gawk test locale', name)\n"
           'VERIFY_LOCALES\n'
           'make -j1 check\n'
           'make -C test -j1 charset-tests\n'
           'make -C test pass-fail']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/gawk-5.4.1; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"; ln -sv gawk.1 "$DESTDIR/usr/share/man/man1/awk.1"']]}
