# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'make -C upstream/gmp-6.3.0 -j4; make -C upstream/gmp-6.3.0 html']],
 'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/gmp-6.3.0; ./configure --prefix=/usr --libdir=/usr/lib --enable-cxx '
                '--disable-static --host=none-linux-gnu --docdir=/usr/share/doc/gmp-6.3.0']],
 'environment': {'CONFIG_SITE': '/dev/null'},
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/gmp-6.3.0 DESTDIR="$DESTDIR" install; make -C upstream/gmp-6.3.0 '
              'DESTDIR="$DESTDIR" install-html']],
 'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              "cd upstream/gmp-6.3.0; sed -i '/long long t1;/,+1s/()/(...)/' configure"]],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'mkdir -p /image-build/output/usr/share/zog-build-evidence/gmp-final; cd '
           'upstream/gmp-6.3.0; make -j1 check 2>&1 | tee '
           '/image-build/output/usr/share/zog-build-evidence/gmp-final/check.log; python3 - '
           "<<'VERIFY'\n"
           'import re,json\n'
           'from pathlib import Path\n'
           'def check_report(text, minimum_passes=199):\n'
           "    keys = ('TOTAL', 'PASS', 'SKIP', 'XFAIL', 'FAIL', 'XPASS', 'ERROR')\n"
           '    totals = dict.fromkeys(keys, 0)\n'
           '    blocks = []\n'
           '    current = None\n'
           '    for line in text.splitlines():\n'
           "        match = re.fullmatch(r'# "
           "(TOTAL|PASS|SKIP|XFAIL|FAIL|XPASS|ERROR):\\s*(\\d+)\\s*', line)\n"
           '        if not match:\n'
           '            continue\n'
           '        key, number = match[1], int(match[2])\n'
           "        if key == 'TOTAL':\n"
           '            if current is not None:\n'
           '                blocks.append(current)\n'
           '            current = {}\n'
           '        if current is None or key in current:\n'
           "            raise ValueError('misordered or duplicate Automake summary')\n"
           '        current[key] = number\n'
           '    if current is not None:\n'
           '        blocks.append(current)\n'
           '    if not blocks:\n'
           "        raise ValueError('no Automake summaries')\n"
           '    for block in blocks:\n'
           "        if set(block) != set(keys) or block['TOTAL'] != sum(block[k] for k in "
           'keys[1:]):\n'
           "            raise ValueError('incomplete or inconsistent Automake summary')\n"
           '        for key in keys:\n'
           '            totals[key] += block[key]\n'
           '    for key in keys[1:]:\n'
           "        observed = sum(bool(re.match(r'^' + key + r':\\s+\\S', line)) for line in "
           'text.splitlines())\n'
           '        if observed != totals[key]:\n'
           "            raise ValueError('individual results disagree with summary: ' + key)\n"
           "    if any(totals[key] for key in ('FAIL', 'XPASS', 'ERROR')):\n"
           "        raise ValueError('unexpected upstream test result')\n"
           "    if totals['PASS'] < minimum_passes:\n"
           "        raise ValueError('insufficient passing tests')\n"
           '    return totals\n'
           '\n'
           "report=Path('/image-build/output/usr/share/zog-build-evidence/gmp-final/check.log')\n"
           'counts=check_report(report.read_text(),199)\n'
           "print('GMP verified test counts:',json.dumps(counts,sort_keys=True))\n"
           "report.with_name('acceptance.json').write_text(json.dumps(counts,sort_keys=True)+'\\n')\n"
           'VERIFY\n']]}
