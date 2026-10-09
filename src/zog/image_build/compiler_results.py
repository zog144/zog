"""Conservative test gates for compiler prerequisites and DejaGNU suites."""
import re


def tcl_report(text):
    rows = re.findall(r'^.*:\s+Total\s+(\d+)\s+Passed\s+(\d+)\s+Skipped\s+(\d+)\s+Failed\s+(\d+)\s*$', text, re.M)
    if not rows:
        raise ValueError('missing Tcl test summary')
    totals = dict.fromkeys(('total', 'passed', 'skipped', 'failed'), 0)
    for row in rows:
        total, passed, skipped, failed = map(int, row)
        if total != passed + skipped + failed or failed:
            raise ValueError('Tcl tests failed or summary is inconsistent')
        for key, value in zip(totals, (total, passed, skipped, failed)):
            totals[key] += value
    if not totals['passed'] or re.search(r'^==== .* FAILED|^Test file error:', text, re.M):
        raise ValueError('Tcl suite error or no passing tests')
    return totals


def dejagnu_report(text):
    if not re.search(r'=== .* Summary ===', text):
        raise ValueError('missing DejaGNU summary')
    counts = {}
    for label, number in re.findall(r'^# of (.+?)\s+(\d+)\s*$', text, re.M):
        counts[label] = counts.get(label, 0) + int(number)
    allowed = {'expected passes', 'expected failures', 'unsupported tests', 'untested testcases'}
    if any(number and label not in allowed for label, number in counts.items()):
        raise ValueError('unexpected DejaGNU result: ' + repr(counts))
    if re.search(r'^(FAIL|XPASS|UNRESOLVED|ERROR):', text, re.M):
        raise ValueError('unaccepted DejaGNU result')
    if counts.get('expected passes', 0) < 1:
        raise ValueError('DejaGNU suite did not pass any tests')
    return counts
