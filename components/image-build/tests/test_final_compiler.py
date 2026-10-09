from pathlib import Path
import json
import pytest
from zog.image_build.compiler_results import tcl_report, dejagnu_report
from zog.image_build.final_compiler import assemble, replacement_records, successful_execution
from zog.image_build.filesystem import inventory
from zog.image_build.metadata import identity, load_packages, order
from zog.image_build.stages import stage_recipes
from zog.image_build.errors import ImageBuildError


def test_tcl_gate_checks_counts_and_hidden_failures():
    assert tcl_report('all.tcl: Total 9 Passed 8 Skipped 1 Failed 0')['passed'] == 8
    for text in ('no tests', 'all.tcl: Total 9 Passed 8 Skipped 1 Failed 1',
                 'all.tcl: Total 9 Passed 8 Skipped 1 Failed 0\n==== test FAILED'):
        with pytest.raises(ValueError): tcl_report(text)


def test_dejagnu_gate_rejects_missing_tests_and_unexpected_results():
    good = '=== gcc Summary ===\n# of expected passes 80\n# of expected failures 2\n# of unsupported tests 3\n'
    assert dejagnu_report(good)['expected passes'] == 80
    for text in ('', '# of expected passes 80', '=== gcc Summary ===',
                 good + '# of unexpected failures 1\n', good + '# of unresolved testcases 2\n',
                 good + 'ERROR: tool failed\n', good + 'XPASS: changed expectation\n'):
        with pytest.raises(ValueError): dejagnu_report(text)


def test_compiler_replacement_preserves_sources_and_rejects_drift(tmp_path):
    base=tmp_path/'base';new=tmp_path/'new'
    for p,value in ((base,'old'),(new,'new')):
        (p/'usr/bin').mkdir(parents=True);(p/'usr/bin/cc').write_text(value)
    (base/'usr/bin/unrelated').write_text('keep')
    records={'outputs':[dict(r,path='sysroot/'+r['path']) for r in inventory(base) if r['path']!='usr/bin/unrelated']}
    before=inventory(base)
    assemble(tmp_path/'result',base,[new],[records])
    assert (tmp_path/'result/usr/bin/cc').read_text()=='new'
    assert (tmp_path/'result/usr/bin/unrelated').read_text()=='keep'
    assert inventory(base)==before
    (base/'usr/bin/cc').write_text('drift')
    with pytest.raises(ImageBuildError,match='changed'):assemble(tmp_path/'bad',base,[new],[records])
    assert (tmp_path/'bad/usr/bin/cc').read_text()=='drift'


def test_ownership_and_completion_must_be_bound(tmp_path):
    path=tmp_path/'old.json';record={'inputs':{'recipe':'old'},'outputs':[{'path':'sysroot/usr/bin/cc'}]}
    record['identity']=identity({'inputs':record['inputs'],'outputs':record['outputs']});path.write_text(json.dumps(record))
    assert replacement_records(path)==record
    record['outputs'].append({'path':'sysroot/changed'})
    path.write_text(json.dumps(record))
    with pytest.raises(ImageBuildError): replacement_records(path)
    record['outputs'].pop()
    record['inputs']['recipe']='changed';path.write_text(json.dumps(record))
    with pytest.raises(ImageBuildError): replacement_records(path)
    (tmp_path/'command-0.execution.json').write_text(json.dumps({'exit_code':0,'cleanup_complete':False}))
    with pytest.raises(ImageBuildError):successful_execution(tmp_path)


def test_final_graph_requires_tools_and_bootstrap(tmp_path):
    catalogue=Path(__file__).resolve().parents[1]/'project/package'
    for stage in ('test-tools','binutils','gcc'):
        target=tmp_path/stage
        plan=stage_recipes(catalogue.parent/('bootstrap/lfs-final-'+stage+'.py'),catalogue,target)
        packages=load_packages(target)
        selected=order(packages,plan['targets'])
        if stage=='test-tools':assert list(selected)==['tcl-final','expect-final','dejagnu-final']
        if stage=='gcc':
            package=packages['gcc-final']
            assert '--enable-bootstrap' in '\n'.join(command[-1] for command in package.steps['configure'])
            assert 'bootstrap' in package.steps['build'][0][-1]
            assert 'make -k -j8 check' in package.steps['test'][0][-1]


def test_gcc_resolver_places_checked_gawk_and_zstd_first(tmp_path):
    catalogue=Path(__file__).resolve().parents[1]/'project/package'
    plan=stage_recipes(catalogue.parent/'bootstrap/lfs-final-gcc.py',catalogue,tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    selected=order(packages,plan['targets'])
    assert selected.index('gawk-final') < selected.index('gcc-final')
    assert selected.index('zstd-final') < selected.index('gcc-final')
    assert 'zstd-final' in packages['gcc-final'].runtime_dependencies
    assert 'HAVE_MPFR' in packages['gawk-final'].steps['configure'][0][-1]
    assert 'Wabsolute-value' in packages['gcc-final'].steps['prepare'][0][-1]
