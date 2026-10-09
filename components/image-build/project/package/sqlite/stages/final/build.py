# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'test -r /usr/lib/tclConfig.sh\n'
                'test -r /usr/include/tcl.h\n'
                'test -r /usr/lib/libtcl8.6.so\n'
                "printf 'puts [info patchlevel]\\n' | /usr/bin/tclsh8.6\n"
                "cat > .zog-tcl-check.c <<'TCL_CHECK'\n"
                '#include <tcl.h>\n'
                'int main(void) { Tcl_FindExecutable("/usr/bin/tclsh8.6"); '
                'Tcl_Interp *i=Tcl_CreateInterp(); int rc=Tcl_Init(i); '
                'Tcl_DeleteInterp(i); Tcl_Finalize(); return rc; }\n'
                'TCL_CHECK\n'
                'cc .zog-tcl-check.c -o .zog-tcl-check -ltcl8.6\n'
                './.zog-tcl-check\n'
                'rm .zog-tcl-check .zog-tcl-check.c\n'
                'cd upstream/sqlite; CFLAGS="-O2 -g -fstack-protector-strong '
                '-D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer '
                '-DSQLITE_ENABLE_API_ARMOR -DSQLITE_ENABLE_COLUMN_METADATA '
                '-DSQLITE_ENABLE_UNLOCK_NOTIFY -DSQLITE_SECURE_DELETE '
                '-DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_STRICT_SUBTYPE=1" '
                'LDFLAGS="-Wl,-z,relro,-z,now" ./configure --prefix=/usr '
                '--libdir=/usr/lib --disable-static --soname=legacy '
                '--enable-threadsafe --enable-load-extension '
                '--with-tcl=/usr/lib --enable-readline --fts3 --fts4 --fts5 '
                '--rtree --session --dbstat; grep -Eq "^HAVE_TCL = 1$" '
                'Makefile; grep -Eq "^TCL_CONFIG_SH = /usr/lib/tclConfig.sh$" '
                'Makefile']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/sqlite; make -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/sqlite\n'
           'make -j8 TCL_CONFIG_SH=/usr/lib/tclConfig.sh testfixture\n'
           './testfixture test/testrunner.tcl --jobs 8 veryquick\n'
           "./sqlite3 -readonly testrunner.db 'SELECT "
           "state,count(*),sum(ntest),sum(nerr) FROM jobs GROUP BY state;'\n"
           'result=$(./sqlite3 -readonly testrunner.db "SELECT CASE WHEN '
           'count(*)>0 AND sum(ntest)>0 AND sum(CASE WHEN '
           "coalesce(state,'')!='done' OR coalesce(nerr,0)!=0 THEN 1 ELSE 0 "
           'END)=0 THEN \'accepted\' ELSE \'rejected\' END FROM jobs;")\n'
           'test "$result" = accepted\n'
           'for required in sessionnoact shell1 zipfile; do\n'
           '  count=$(./sqlite3 -readonly testrunner.db "SELECT count(*) FROM '
           "jobs WHERE displayname LIKE '%$required.test%' AND state='done' "
           'AND ntest>0 AND nerr=0;")\n'
           '  test "$count" -gt 0\n'
           'done\n'
           "echo 'SQLite isolated veryquick suite accepted; all jobs done, "
           "zero errors, regression files included'\n"]],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/sqlite; make DESTDIR="$DESTDIR" install; test -f '
              '"$DESTDIR/usr/include/sqlite3.h"']]}
