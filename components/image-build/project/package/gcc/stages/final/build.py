# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C build -j8 bootstrap']],
 'configure': [['/bin/sh',
                '-ec',
                'set -eu\n'
                'cd /image-build/source/upstream/gcc-15.3.0\n'
                'patch --batch --forward --fuzz=0 -p1 -i '
                '/image-build/source/patches/strchr-c23.patch\n'
                'patch --batch --forward --fuzz=0 -p1 -i '
                '/image-build/source/patches/cpython-gcc15.patch\n'
                "printf '%s\\n' '1b33eb7b83faf2cafbe8b755fc3059f78c10c7a6a8bf4af828ec36ff6b5a579b  "
                "gcc/testsuite/gcc.dg/plugin/analyzer_cpython_plugin.cc' | sha256sum -c -\n"],
               ['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'mkdir build; cd build; ../upstream/gcc-15.3.0/configure --prefix=/usr '
                '--build=x86_64-zog-linux-gnu --host=x86_64-zog-linux-gnu '
                '--target=x86_64-zog-linux-gnu LD=ld --enable-languages=c,c++ --enable-default-pie '
                '--enable-default-ssp --enable-host-pie --enable-targets=all --disable-multilib '
                '--enable-bootstrap --enable-checking=yes --disable-fixincludes --with-system-zlib '
                '--with-zstd --without-isl --disable-libgdiagnostics'],
               ['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'make -C build configure-gcc\n'
                'make -C build/gcc options.cc\n'
                'if grep -n "^#error" build/gcc/options.cc; then exit 1; fi\n'
                'echo "GCC option generation accepted"']],
 'environment': {'CONFIG_SITE': '/dev/null'},
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C build DESTDIR="$DESTDIR" install\n'
              'ln -s gcc "$DESTDIR/usr/bin/cc"\n'
              'ln -s ../bin/cpp "$DESTDIR/usr/lib/cpp"\n'
              'mkdir -p "$DESTDIR/usr/lib/bfd-plugins"\n'
              'ln -s ../gcc/x86_64-zog-linux-gnu/15.3.0/liblto_plugin.so '
              '"$DESTDIR/usr/lib/bfd-plugins/liblto_plugin.so"\n']],
 'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'test "$(gawk \'BEGIN { if (a["x"] == "") n++; a["x"] = a["x"] "Wabsolute-value"; '
              'print a["x"] }\')" = Wabsolute-value\n'
              'gawk -M \'BEGIN { if (!("mpfr_version" in PROCINFO)) exit 1; print "Verified Gawk '
              'MPFR", PROCINFO["mpfr_version"] }\'\n'
              'test -f /usr/include/zstd.h; test -e /usr/lib/libzstd.so'],
             ['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              "sed -i '/m64=/s/lib64/lib/' upstream/gcc-15.3.0/gcc/config/i386/t-linux64"]],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'ulimit -s 262144\n'
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/gcc-final; cd build; set +e; '
           'make -k -j8 check 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/gcc-final/check.log; '
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
           'p=Path("/image-build/output/usr/share/zog-build-evidence/gcc-final"); '
           'reports=list(Path(".").rglob("*.sum")); counts={}\n'
           'if not reports: raise ValueError("No compiler suite summaries")\n'
           'for report in reports:\n'
           ' text=report.read_text(errors="replace")\n'
           ' if " Summary ===" not in text: continue\n'
           ' target=p/"summaries"/report; target.parent.mkdir(parents=True,exist_ok=True); '
           'target.write_text(text)\n'
           ' counts[str(report)]=dejagnu_report(text)\n'
           'if not counts: raise ValueError("No completed compiler suites")\n'
           "required=['gcc.sum', 'g++.sum', 'libstdc++.sum']\n"
           'if not set(required).issubset({Path(x).name for x in counts}): raise '
           'ValueError("Missing required compiler suites: "+repr(required))\n'
           '(p/"acceptance.json").write_text(json.dumps(counts,sort_keys=True,indent=2)+"\\n")\n'
           'print(json.dumps(counts,sort_keys=True))\n'
           'VERIFY\n'
           'test "$status" -eq 0']]}
