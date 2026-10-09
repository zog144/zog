from pathlib import Path
import json
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages, order
PROJECT=Path(__file__).parents[1]/'project'

def test_native_prerequisite_graph_is_pinned(tmp_path):
    plan=stage_recipes(PROJECT/'bootstrap/rust-prerequisites.py',PROJECT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    sequence=order(packages,plan['targets'])
    assert sequence.index('pkgconf-final') < sequence.index('curl-final')
    assert set(sequence)=={'cmake-final','pkgconf-final','curl-final'}
    for p in packages.values():
        assert p.licensing['evidence']
        assert all(s['archive'] for s in p.sources)


def test_native_report_binds_specific_check(tmp_path):
    from test_installed_verification import scenario
    from zog.image_build import installed_verification as iv, generation_provenance as gp
    from zog.image_build.filesystem import write_json
    from zog.image_build.metadata import identity
    # Check name is part of the frozen generation, not inferred from its logs.
    s=scenario(tmp_path)
    legacy=iv.capture(s.p,s.binding,s.root,s.owner,s.check,s.execution)
    assert json.loads((s.p.root/'artifacts'/legacy['digest'][7:]).read_bytes())['check']=='installed-trust'
    changed=dict(s.owner,verification_check='installed-native-tools')
    import pytest
    from zog.image_build.errors import ImageBuildError
    with pytest.raises(ImageBuildError,match='owner inputs differ'):
        iv.capture(s.p,s.binding,s.root,changed,s.check,s.execution)


def test_rust_seed_is_pinned_and_build_only(tmp_path):
    plan=stage_recipes(PROJECT/'bootstrap/rust-toolchain.py',PROJECT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes');rust=packages['rust-final']
    assert order(packages,plan['targets'])[-1]=='rust-final'
    seeds=rust.integration['bootstrap_seed']['components']
    assert len(seeds)==3
    assert {s['sha256'] for s in seeds} <= {s['sha256'] for s in rust.sources}
    assert rust.environment['CARGO_NET_OFFLINE']=='true'
    prepare=rust.steps['prepare'][0][-1]
    assert 'download-ci-llvm = false' in prepare and 'download-rustc = false' in prepare
    assert 'locked-deps = true' in prepare and 'vendor = true' in prepare
    assert all(s['destination'].startswith('seed-') for s in rust.sources[1:])
    assert 'bootstrap' not in rust.steps['install'][0][-1]
    assert 'library/std --no-fail-fast' in rust.steps['test'][0][-1]


def test_retained_outputs_require_exact_binding_and_bytes(tmp_path):
    from zog.image_build.native_tools import retained_output
    from zog.image_build.filesystem import inventory, write_json
    import pytest
    base=tmp_path/'image-build/attempts'
    a=base/'a/packages/example'; b=base/'b/packages/example'
    for folder in (a,b):
        (folder/'output').mkdir(parents=True)
        (folder/'output/file').write_text('accepted')
    record={'identity':'test','outputs':inventory(a/'output'),
            'provenance':{'output':'output-record','result':'result-record'}}
    write_json(a/'result.json',{k:v for k,v in record.items() if k!='provenance'})
    write_json(a/'provenance.json',record['provenance'])
    write_json(b/'result.json',record)
    assert retained_output(tmp_path,'example',record)==a/'output'
    (a/'output/file').write_text('corrupt')
    assert retained_output(tmp_path,'example',record)==b/'output'
    write_json(b/'result.json',dict(record,provenance={'output':'different','result':'different'}))
    with pytest.raises(ValueError,match='exact provenance'):
        retained_output(tmp_path,'example',record)


def test_rust_completion_is_declared():
    import ast
    manifest=ast.literal_eval((PROJECT/'package/rust/stages/final/produce-manifest.py').read_text())
    assert 'etc/bash_completion.d' in manifest['trees']
    assert 'etc/bash_completion.d/cargo' in manifest['required']
