import ast
from pathlib import Path
import pytest
from jobs.gcc_pin_build import verify_summary
from zog.image_build.stages import stage_recipes


@pytest.mark.parametrize('result', ['FAIL', 'XPASS', 'UNRESOLVED', 'ERROR'])
def test_pin_gate_rejects_unexpected_even_with_passes(result):
    with pytest.raises(ValueError):
        verify_summary('=== gcc Summary ===\n# of expected passes 2\n'+result+': regression\n')


@pytest.mark.parametrize('text', ['# of expected passes 2',
    '=== gcc Summary ===\n# of unsupported tests 3',
    '=== gcc Summary ===\n# of expected passes 2\n# of unexpected failures 1'])
def test_pin_gate_rejects_missing_coverage_and_failure_counts(text):
    with pytest.raises(ValueError):
        verify_summary(text)


def test_pin_stage_uses_version_bound_license(tmp_path):
    root = Path(__file__).resolve().parents[1]/'project'
    stage_recipes(root/'bootstrap/lfs-final-gcc.py', root/'package', tmp_path/'recipes')
    recipe = tmp_path/'recipes/gcc-final'
    source = ast.literal_eval((recipe/'sources.py').read_text())[0]
    license_record = ast.literal_eval((recipe/'license.py').read_text())
    assert license_record['version'] == '15.3.0'
    assert source['sha256'] == license_record['source']['sha256']
    assert all(e['source_sha256'] == source['sha256'] for e in license_record['evidence'])
    assert verify_summary('=== gcc Summary ===\n# of expected passes 2\n# of expected failures 1')['expected passes'] == 2


def test_full_suite_does_not_disable_explicit_hardening():
    root = Path(__file__).resolve().parents[1]
    build = ast.literal_eval((root/'project/package/gcc/stages/final/build.py').read_text())
    assert 'RUNTESTFLAGS=--target_board=unix/-fno-pie' not in build['test'][0][-1]


def test_gcc_final_backports_use_immutable_public_sources():
    root = Path(__file__).resolve().parents[1]
    stage = root / 'project/package/gcc/stages/final'
    sources = ast.literal_eval((stage/'sources.py').read_text())
    integration = ast.literal_eval((stage/'integration.py').read_text())
    pin = ast.literal_eval((root/'project/pins/2026-10-01/commit-pin.py').read_text())

    public_commit = '8aeb6ad76402a9f91d6408e445190b4c03dd69f8'
    base = f'https://raw.githubusercontent.com/zog144/zog/{public_commit}/third-party/gcc/patches'
    expected = {
        'patches/strchr-c23.patch': (
            f'{base}/strchr-c23.patch',
            '312cbc23d95b25d17141f2b90dec8a273b2eaacb21d2e0a8bc07f64d5b26baaf',
        ),
        'patches/cpython-gcc15.patch': (
            f'{base}/cpython-gcc15.patch',
            '5b302894ccebee465679e8770b6e60de2356ead428674b4873aaa1081fe18031',
        ),
    }

    by_destination = {item['destination']: item for item in sources}
    for destination, (url, digest) in expected.items():
        assert by_destination[destination]['url'] == url
        assert by_destination[destination]['sha256'] == digest
        assert not by_destination[destination]['url'].startswith('recipe:')

    assert integration['version'] == '15.3.0'
    integrated = {item['source']['destination']: item['source']
                  for item in integration['test_fixture_backports']}
    for destination, (url, digest) in expected.items():
        assert integrated[destination]['url'] == url
        assert integrated[destination]['sha256'] == digest

    pinned = {item['destination']: item
              for item in pin['packages']['gcc']['recipes']['gcc/stages/final']}
    for destination, (url, digest) in expected.items():
        assert pinned[destination]['url'] == url
        assert pinned[destination]['sha256'] == digest

    assert not (stage/'patches/strchr-c23.patch').exists()
    assert not (stage/'patches/cpython-gcc15.patch').exists()
