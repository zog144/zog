import pytest
from zog.image_build.info_index import HEADER,compose,entries
from zog.image_build.filesystem import merge,inventory
from zog.image_build.errors import ImageBuildError

A=HEADER+'\nLibraries\n* GMP: (gmp). Numbers.\n    Continued description.\n'
B=HEADER+'\nLibraries\n* MPFR: (mpfr). Floats.\n'


def test_union_is_deterministic_and_keeps_wrapped_entries():
    assert compose(A,B)==compose(B,A)==compose(A,B,A)
    assert entries(compose(A,B))=={**entries(A),**entries(B)}


@pytest.mark.parametrize('text',[A.replace('Numbers.', 'Conflicting description.'), A.replace('* GMP:', '* bad syntax'), 'invalid header'])
def test_conflicting_or_unknown_contribution_rejected(text):
    with pytest.raises(ImageBuildError):compose(A,text)


def test_only_explicit_index_policy_relaxes_ownership(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';root=tmp_path/'root'
    for p,text in ((a,A),(b,B)):
        (p/'usr/share/info').mkdir(parents=True);(p/'usr/share/info/dir').write_text(text)
    original=inventory(a),inventory(b)
    merge(a,root)
    with pytest.raises(ImageBuildError,match='ownership'):merge(b,root)
    merge(b,root,compose_info=True)
    assert (root/'usr/share/info/dir').read_text()==compose(A,B)
    assert original==(inventory(a),inventory(b))
    (a/'usr/share/info/ordinary').write_text('one');(b/'usr/share/info/ordinary').write_text('two')
    other=tmp_path/'other';merge(a,other,compose_info=True)
    with pytest.raises(ImageBuildError,match='ownership'):merge(b,other,compose_info=True)


def test_index_symlink_refused(tmp_path):
    a=tmp_path/'a';root=tmp_path/'root';(a/'usr/share/info').mkdir(parents=True)
    (a/'usr/share/info/dir').symlink_to('/etc/passwd')
    with pytest.raises(ImageBuildError,match='regular'):merge(a,root,compose_info=True)


def test_same_label_may_reference_distinct_nodes():
    text=HEADER+'\nFunctions\n* O_NONBLOCK: (libc)Open-time Flags.\n* O_NONBLOCK: (libc)Operating Modes.\n'
    assert len(entries(compose(text,text)))==2
    assert 'Open-time Flags.' in compose(text) and 'Operating Modes.' in compose(text)


def test_engine_dependency_and_final_composition(tmp_path):
    from test_source_build import recipe,RecordingRunner
    from zog.image_build.engine import ImageBuild
    from zog.image_build.info_index import POLICY
    from zog.image_build.metadata import load_packages
    recipes=tmp_path/'recipes'
    recipe(recipes,'library',outputs=['usr/share/info/dir','usr/share/library'])
    recipe(recipes,'consumer',runtime=['library'],outputs=['usr/share/consumer','usr/share/info/dir'])
    class Runner(RecordingRunner):
        def run(self,root,source,output,arguments,environment,log):
            if arguments==['compile','consumer']:
                assert '* GMP:' in (root/'usr/share/info/dir').read_text()
                assert '* Base:' in (root/'usr/share/info/dir').read_text()
            super().run(root,source,output,arguments,environment,log)
            if arguments[0]=='install':
                path=output/'usr/share/info/dir';path.parent.mkdir(parents=True)
                path.write_text(A if arguments[1]=='library' else B)
    builder=ImageBuild(package_dir=recipes,state_dir=tmp_path/'state',runner=Runner())
    base=tmp_path/'base';(base/'usr/share/info').mkdir(parents=True)
    (base/'usr/share/info/dir').write_text(HEADER+'\nTools\n* Base: (base). Base.\n')
    seed=builder.import_bootstrap(base,{})
    attempt=tmp_path/'attempt';attempt.mkdir()
    packages=load_packages(recipes)
    built=builder._build_set(packages,['consumer'],seed,attempt)
    assert 'composition_policy' not in built['library']['inputs']
    assert built['consumer']['inputs']['composition_policy']==POLICY
    builder._compose(packages,['consumer'],built,attempt/'composed')
    assert (attempt/'composed/usr/share/info/dir').read_text()==compose(A,B)
    assert (built['library']['root']/'usr/share/info/dir').read_text()==A
