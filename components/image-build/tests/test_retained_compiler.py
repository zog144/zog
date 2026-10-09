from copy import deepcopy
from types import SimpleNamespace
import pytest
from zog.image_build.retained_compiler import passed_job, passed_suite, installed_acceptance
from zog.image_build.errors import ImageBuildError


def test_retained_acceptance_requires_completed_controller_cleanup():
    good = {'state':'completed', 'exit_code':0, 'process_cleanup_complete':True}
    assert passed_job(SimpleNamespace(refresh_build_job=lambda _:good), 'job') == good
    for field,value in [('state','running'), ('exit_code',1), ('process_cleanup_complete',False)]:
        bad = dict(good, **{field:value})
        with pytest.raises(ImageBuildError):
            passed_job(SimpleNamespace(refresh_build_job=lambda _:bad), 'job')


def test_retained_full_suite_rejects_missing_or_unexpected_results():
    good = {'status':'tests-passed','command_exit':0,'failures':[],'missing':[],
            'suites':{name:{'expected passes':2} for name in ['gcc.sum','g++.sum','libstdc++.sum']}}
    assert passed_suite(good) == good
    for change in ['missing', 'failure', 'zero', 'unexpected']:
        bad = deepcopy(good)
        if change == 'missing': del bad['suites']['g++.sum']
        if change == 'failure': bad['failures'] = ['FAIL: test']
        if change == 'zero': bad['suites']['gcc.sum']['expected passes'] = 0
        if change == 'unexpected': bad['suites']['gcc.sum']['unexpected successes'] = 1
        with pytest.raises(ImageBuildError): passed_suite(bad)


def test_installed_acceptance_keeps_runtime_checks_for_pinned_version():
    command = installed_acceptance('15.3.0')
    assert '= 15.3.0' in command and '= 16.2.0' not in command
    assert '-flto' in command and 'RPATH|RUNPATH' in command and 'forbidden-write' in command
    with pytest.raises(ImageBuildError): installed_acceptance('16.2.0')
