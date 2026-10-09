# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-c',
                'cd upstream/perl-5.44.0; sh Configure -des -Dprefix=/usr -Dvendorprefix=/usr -Duseshrplib '
                '-Dman1dir=/usr/share/man/man1 -Dman3dir=/usr/share/man/man3 -Dman1ext=1 -Dman3ext=3 '
                '-Dprivlib=/usr/lib/perl5/5.44/core_perl -Darchlib=/usr/lib/perl5/5.44/core_perl '
                '-Dsitelib=/usr/lib/perl5/5.44/site_perl -Dsitearch=/usr/lib/perl5/5.44/site_perl '
                '-Dvendorlib=/usr/lib/perl5/5.44/vendor_perl -Dvendorarch=/usr/lib/perl5/5.44/vendor_perl']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/perl-5.44.0; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/perl-5.44.0; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
