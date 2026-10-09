# Data only; parsed with ast.literal_eval.
{'environment': {'CONFIG_SITE': '/dev/null'},
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'mkdir build; cd build; ../upstream/dejagnu-1.6.3/configure --prefix=/usr']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C build -j4']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/dejagnu-final; cd build; set '
           '+e; make check 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/dejagnu-final/check.log; '
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
           'p=Path("/image-build/output/usr/share/zog-build-evidence/dejagnu-final"); '
           'reports=list(Path(".").rglob("*.sum")); counts={}\n'
           'if not reports: raise ValueError("No compiler suite summaries")\n'
           'for report in reports:\n'
           ' text=report.read_text(errors="replace")\n'
           ' if " Summary ===" not in text: continue\n'
           ' target=p/"summaries"/report; target.parent.mkdir(parents=True,exist_ok=True); '
           'target.write_text(text)\n'
           ' counts[str(report)]=dejagnu_report(text)\n'
           'if not counts: raise ValueError("No completed compiler suites")\n'
           '(p/"acceptance.json").write_text(json.dumps(counts,sort_keys=True,indent=2)+"\\n")\n'
           'print(json.dumps(counts,sort_keys=True))\n'
           'VERIFY\n'
           'test "$status" -eq 0']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C build DESTDIR="$DESTDIR" install']]}
