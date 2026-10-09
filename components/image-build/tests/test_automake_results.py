from pathlib import Path
import ast
import inspect
import pytest
from zog.image_build.automake_results import check_report


def report(passed=199, skipped=1, failed=0):
    lines=['PASS: test-'+str(n) for n in range(passed)]
    lines += ['SKIP: optional-'+str(n) for n in range(skipped)]
    lines += ['FAIL: failed-'+str(n) for n in range(failed)]
    counts={'TOTAL':passed+skipped+failed,'PASS':passed,'SKIP':skipped,'XFAIL':0,'FAIL':failed,'XPASS':0,'ERROR':0}
    return '\n'.join(lines+['# '+k+': '+str(v) for k,v in counts.items()])


def test_multiple_suites_and_skip():
    assert check_report(report(100,1)+'\n'+report(99,0))['PASS']==199


@pytest.mark.parametrize('text',[report(198),report(failed=1),report().replace('# ERROR: 0',''),report().replace('# TOTAL: 200','# TOTAL: 201'),report().replace('PASS: test-0','unrecognized result'), ''])
def test_rejects_failure_missing_or_inconsistent_evidence(text):
    with pytest.raises(ValueError):check_report(text)


def test_recipe_embeds_reviewed_parser():
    recipe=Path(__file__).parents[1]/'project/package/gmp/stages/final/build.py'
    commands=ast.literal_eval(recipe.read_text())['test']
    assert inspect.getsource(check_report) in commands[0][-1]
    assert 'pipefail' in commands[0]
