"""Validate Automake's captured check output, not individual test log wording."""
import re


def check_report(text, minimum_passes=199):
    keys = ('TOTAL', 'PASS', 'SKIP', 'XFAIL', 'FAIL', 'XPASS', 'ERROR')
    totals = dict.fromkeys(keys, 0)
    blocks = []
    current = None
    for line in text.splitlines():
        match = re.fullmatch(r'# (TOTAL|PASS|SKIP|XFAIL|FAIL|XPASS|ERROR):\s*(\d+)\s*', line)
        if not match:
            continue
        key, number = match[1], int(match[2])
        if key == 'TOTAL':
            if current is not None:
                blocks.append(current)
            current = {}
        if current is None or key in current:
            raise ValueError('misordered or duplicate Automake summary')
        current[key] = number
    if current is not None:
        blocks.append(current)
    if not blocks:
        raise ValueError('no Automake summaries')
    for block in blocks:
        if set(block) != set(keys) or block['TOTAL'] != sum(block[k] for k in keys[1:]):
            raise ValueError('incomplete or inconsistent Automake summary')
        for key in keys:
            totals[key] += block[key]
    for key in keys[1:]:
        observed = sum(bool(re.match(r'^' + key + r':\s+\S', line)) for line in text.splitlines())
        if observed != totals[key]:
            raise ValueError('individual results disagree with summary: ' + key)
    if any(totals[key] for key in ('FAIL', 'XPASS', 'ERROR')):
        raise ValueError('unexpected upstream test result')
    if totals['PASS'] < minimum_passes:
        raise ValueError('insufficient passing tests')
    return totals
