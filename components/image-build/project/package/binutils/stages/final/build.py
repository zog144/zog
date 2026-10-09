# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C build -j4 tooldir=/usr']],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'for tool in bzip2 flex bc dc; do command -v "$tool"; done; bzip2 --help '
                '>/dev/null 2>&1; flex --version; printf "6*7\\n" | bc | grep -x 42; printf "6 7 * '
                'p\\n" | dc | grep -x 42'],
               ['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'mkdir build; cd build; ../upstream/binutils-2.47/configure --prefix=/usr '
                '--sysconfdir=/etc --enable-ld=default --enable-plugins --enable-shared '
                '--disable-werror --enable-64-bit-bfd --enable-new-dtags --with-system-zlib '
                '--with-lib-path=/usr/lib --enable-default-hash-style=gnu']],
 'environment': {'CONFIG_SITE': '/dev/null'},
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C build DESTDIR="$DESTDIR" tooldir=/usr install']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/binutils-final; cd build; '
           'set +e; make -k -j4 check 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/binutils-final/check.log; '
           'status=${PIPESTATUS[0]}; set -e\n'
           "python3 - <<'VERIFY'\n"
           'import re,json\n'
           'from pathlib import Path\n'
           'def dejagnu_report(text):\n'
           "    if not re.search(r'=== .* Summary ===', text):\n"
           "        raise ValueError('missing DejaGNU summary')\n"
           '    counts = {}\n'
           "    for label, number in re.findall(r'^# of (.+?)\\s+(\\d+)\\s*$', text, re.M):\n"
           '        counts[label] = counts.get(label, 0) + int(number)\n'
           "    allowed = {'expected passes', 'expected failures', 'unsupported tests', 'untested "
           "testcases'}\n"
           '    if any(number and label not in allowed for label, number in counts.items()):\n'
           "        raise ValueError('unexpected DejaGNU result: ' + repr(counts))\n"
           "    if re.search(r'^(FAIL|XPASS|UNRESOLVED|ERROR):', text, re.M):\n"
           "        raise ValueError('unaccepted DejaGNU result')\n"
           "    if counts.get('expected passes', 0) < 1:\n"
           "        raise ValueError('DejaGNU suite did not pass any tests')\n"
           '    return counts\n'
           '\n'
           'p=Path("/image-build/output/usr/share/zog-build-evidence/binutils-final"); '
           'reports=list(Path(".").rglob("*.sum")); counts={}\n'
           'if not reports: raise ValueError("No compiler suite summaries")\n'
           'for report in reports:\n'
           ' text=report.read_text(errors="replace")\n'
           ' if " Summary ===" not in text: continue\n'
           ' target=p/"summaries"/report; target.parent.mkdir(parents=True,exist_ok=True); '
           'target.write_text(text)\n'
           ' counts[str(report)]=dejagnu_report(text)\n'
           'if not counts: raise ValueError("No completed compiler suites")\n'
           "required=['binutils.sum', 'gas.sum', 'ld.sum']\n"
           'if not set(required).issubset({Path(x).name for x in counts}): raise '
           'ValueError("Missing required compiler suites: "+repr(required))\n'
           '(p/"acceptance.json").write_text(json.dumps(counts,sort_keys=True,indent=2)+"\\n")\n'
           'print(json.dumps(counts,sort_keys=True))\n'
           'VERIFY\n'
           'test "$status" -eq 0']],
 'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/binutils-2.47\n'
              "printf '%s  %s\\n' "
              "'490f1e5673dd349a1269f7317923ffb8617354a34bc8a545f79718bc3ae9bc9b' "
              "'gprofng/src/gp-gmon.cc' | sha256sum -c -\n"
              "printf '%s  %s\\n' "
              "'cc4aaa5749b3b6cb3d5296ec1485c667c8e438dbd32b1530025e19cf95896060' "
              "'../../patches/gprofng-34502.patch' | sha256sum -c -\n"
              'patch --batch --forward --fuzz=0 -p1 --dry-run < ../../patches/gprofng-34502.patch\n'
              'patch --batch --forward --fuzz=0 -p1 < ../../patches/gprofng-34502.patch\n'
              "printf '%s  %s\\n' "
              "'b95236fb781bb659adaf9c278a37edc08b0922ff583ff47c16b8cda121e6246a' "
              "'gprofng/src/gp-gmon.cc' | sha256sum -c -\n"
              "printf 'Applied reviewed upstream patch gprofng-34502 "
              "(2d570d754422b4990f590829c4bed905a327bc7b)\\n'\n"]]}
