# Data only; parsed with ast.literal_eval.
{'environment': {'CONFIG_SITE': '/dev/null'},
 'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/expect5.45.4; patch -Np1 -i ../../gcc15.patch']],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/expect5.45.4; ./configure --prefix=/usr --with-tcl=/usr/lib '
                '--enable-shared --disable-rpath --mandir=/usr/share/man '
                '--with-tclinclude=/usr/include']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C upstream/expect5.45.4 -j4']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/expect-final; cd '
           'upstream/expect5.45.4; set +e; make test 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/expect-final/check.log; '
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
           "    if not totals['passed'] or re.search(r'^==== .* FAILED|^Test file error:', text, "
           're.M):\n'
           "        raise ValueError('Tcl suite error or no passing tests')\n"
           '    return totals\n'
           '\n'
           'p=Path("/image-build/output/usr/share/zog-build-evidence/expect-final"); '
           'counts=tcl_report((p/"check.log").read_text())\n'
           '(p/"acceptance.json").write_text(json.dumps(counts,sort_keys=True,indent=2)+"\\n")\n'
           'print(json.dumps(counts,sort_keys=True))\n'
           'VERIFY\n'
           'test "$status" -eq 0']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/expect5.45.4 DESTDIR="$DESTDIR" install; ln -s '
              'expect5.45.4/libexpect5.45.4.so "$DESTDIR/usr/lib/libexpect5.45.4.so"']]}
