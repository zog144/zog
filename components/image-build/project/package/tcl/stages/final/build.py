# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'make -C upstream/tcl8.6.18/unix -j4']],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                "python3 - <<'FEATURES'\n"
                'from pathlib import Path\n'
                'import shutil\n'
                "root=Path('upstream/tcl8.6.18')\n"
                "policy={'included': ['itcl4.3.7', 'sqlite3.53.0', 'tdbc1.1.13', "
                "'tdbcsqlite3-1.1.13', 'thread2.8.13'], 'excluded': {'tdbcmysql1.1.13': "
                "['MySQL client library and test database'], 'tdbcodbc1.1.13': ['ODBC driver "
                "manager, drivers and test databases'], 'tdbcpostgres1.1.13': ['PostgreSQL "
                "client library and test database']}}\n"
                "expected=set(policy['included']) | set(policy['excluded'])\n"
                "present={p.name for p in (root/'pkgs').iterdir() if p.is_dir()}\n"
                "assert present==expected, ('Unexpected bundled Tcl packages', "
                'sorted(present))\n'
                "excluded=root/'excluded-bundled';excluded.mkdir()\n"
                "for name,requirements in policy['excluded'].items():\n"
                "    shutil.move(str(root/'pkgs'/name),str(excluded/name))\n"
                "    print('Disabled optional Tcl adapter:',name,'; requires',', "
                "'.join(requirements),flush=True)\n"
                "assert {p.name for p in (root/'pkgs').iterdir() if "
                "p.is_dir()}==set(policy['included'])\n"
                'FEATURES\n'
                'cd upstream/tcl8.6.18/unix; ./configure --prefix=/usr '
                '--mandir=/usr/share/man --disable-rpath']],
 'environment': {'CONFIG_SITE': '/dev/null', 'USER': 'build-user', 'LOGNAME': 'build-user'},
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/tcl8.6.18\n'
              'src=$(pwd)\n'
              'sed -i -e "s|$src/unix|/usr/lib|g" -e "s|$src|/usr/include|g" '
              'unix/tclConfig.sh\n'
              'sed -i -e "s|$src/unix/pkgs/tdbc1.1.13|/usr/lib/tdbc1.1.13|g" -e '
              '"s|$src/pkgs/tdbc1.1.13/generic|/usr/include|g" -e '
              '"s|$src/pkgs/tdbc1.1.13/library|/usr/lib/tcl8.6|g" -e '
              '"s|$src/pkgs/tdbc1.1.13|/usr/include|g" unix/pkgs/tdbc1.1.13/tdbcConfig.sh\n'
              'sed -i -e "s|$src/unix/pkgs/itcl4.3.7|/usr/lib/itcl4.3.7|g" -e '
              '"s|$src/pkgs/itcl4.3.7/generic|/usr/include|g" -e '
              '"s|$src/pkgs/itcl4.3.7|/usr/include|g" unix/pkgs/itcl4.3.7/itclConfig.sh\n'
              'make -C unix DESTDIR="$DESTDIR" install\n'
              'make -C unix DESTDIR="$DESTDIR" install-private-headers\n'
              'chmod 644 "$DESTDIR/usr/lib/libtclstub8.6.a"\n'
              'chmod u+w "$DESTDIR/usr/lib/libtcl8.6.so"\n'
              'ln -s tclsh8.6 "$DESTDIR/usr/bin/tclsh"\n'
              'mv "$DESTDIR/usr/share/man/man3/Thread.3" '
              '"$DESTDIR/usr/share/man/man3/Tcl_Thread.3"\n'
              '\n'
              'for package in tdbcmysql1.1.13 tdbcodbc1.1.13 tdbcpostgres1.1.13; do test ! -e '
              '"$DESTDIR/usr/lib/$package"; done\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           "python3 - <<'ENVIRONMENT'\n"
           'import os,pwd,grp,locale,subprocess\n'
           "assert pwd.getpwuid(os.getuid()).pw_name==os.environ['USER']=='build-user'\n"
           "assert pwd.getpwuid(os.getuid()).pw_dir==os.environ['HOME']\n"
           "assert grp.getgrgid(os.getgid()).gr_name=='build-user'\n"
           "assert pwd.getpwnam('root').pw_uid==0\n"
           "locale.setlocale(locale.LC_ALL,'C.UTF-8')\n"
           "assert locale.nl_langinfo(locale.CODESET)=='UTF-8'\n"
           "r=subprocess.run(['/bin/sh','-c','printf "
           "clean-stderr'],env=dict(os.environ,LC_ALL='C.UTF-8'),capture_output=True,check=True)\n"
           "assert r.stdout==b'clean-stderr' and not r.stderr\n"
           "print('Tcl account and locale preflight passed',flush=True)\n"
           'ENVIRONMENT\n'
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/tcl-final; cd '
           'upstream/tcl8.6.18/unix; set +e; LC_ALL=C.UTF-8 make test 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/tcl-final/check.log; '
           'status=${PIPESTATUS[0]}; set -e\n'
           "python3 - <<'VERIFY'\n"
           'import re,json\n'
           'from pathlib import Path\n'
           'def tcl_report(text):\n'
           '    rows = '
           "re.findall(r'^.*:\\s+Total\\s+(\\d+)\\s+Passed\\s+(\\d+)\\s+Skipped\\s+(\\d+)\\s+Failed\\s+(\\d+)\\s*$', "
           'text, re.M)\n'
           '    if not rows:\n'
           "        raise ValueError('missing Tcl test summary')\n"
           "    totals = dict.fromkeys(('total', 'passed', 'skipped', 'failed'), 0)\n"
           '    for row in rows:\n'
           '        total, passed, skipped, failed = map(int, row)\n'
           '        if total != passed + skipped + failed or failed:\n'
           "            raise ValueError('Tcl tests failed or summary is inconsistent')\n"
           '        for key, value in zip(totals, (total, passed, skipped, failed)):\n'
           '            totals[key] += value\n'
           "    if not totals['passed'] or re.search(r'^==== .* FAILED|^Test file error:', "
           'text, re.M):\n'
           "        raise ValueError('Tcl suite error or no passing tests')\n"
           '    return totals\n'
           '\n'
           'p=Path("/image-build/output/usr/share/zog-build-evidence/tcl-final"); '
           'counts=tcl_report((p/"check.log").read_text())\n'
           '(p/"acceptance.json").write_text(json.dumps(counts,sort_keys=True,indent=2)+"\\n")\n'
           'print(json.dumps(counts,sort_keys=True))\n'
           'VERIFY\n'
           'test "$status" -eq 0']]}
