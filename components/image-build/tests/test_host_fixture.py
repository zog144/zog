import os
from pathlib import Path

import pytest

from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory
from zog.image_build.host_export import verify
from zog.image_build.host_fixture import generate
from zog.image_build.host_inventory import inspect

PROJECT = Path(__file__).resolve().parents[1]


def test_fixture_outcomes_and_reproducibility(tmp_path):
    first = generate(tmp_path/'a')
    previous = os.umask(0o077)
    try: second = generate(tmp_path/'b')
    finally: os.umask(previous)
    assert first == second
    for case in first['cases']:
        a = tmp_path/'a'/case['directory']; b = tmp_path/'b'/case['directory']
        for p in a.iterdir(): assert p.read_bytes() == (b/p.name).read_bytes()
        if case['verify'] == 'accept':
            assert verify(a, case['expected_id'])['readiness']['installable'] is False
        else:
            with pytest.raises(ImageBuildError): verify(a, case['expected_id'])
    assert not (tmp_path/'escape').exists()
    with pytest.raises(ImageBuildError, match='must be new'): generate(tmp_path/'a')


def test_committed_fixtures_match_generator(tmp_path):
    generate(tmp_path/'generated')
    committed = PROJECT/'examples/host-install/fixtures'
    for p in committed.rglob('*'):
        if p.is_file(): assert p.read_bytes() == (tmp_path/'generated'/p.relative_to(committed)).read_bytes()


def test_inventory_distinguishes_metadata_stages_and_acceptance():
    report = inspect(PROJECT/'project/host/bootstrap-profile.py', PROJECT/'project/package')
    items = {i['project']:i for i in report['items']}
    assert not report['installable'] and report['live_inventory'] == 'not-performed'
    assert items['python']['stages'] and not items['python']['recipe_gap']
    assert items['python']['host_acceptance'] == 'not-assessed'
    assert items['openssl']['catalogue_present'] and not items['openssl']['recipe_gap']
    assert items['openssl']['host_acceptance'] == 'not-assessed'
    assert items['linux']['stages']
    assert 'foreign' in items['linux']['role']


def test_metadata_alone_never_counts_as_recipe(tmp_path):
    root = tmp_path/'package'; (root/'python/stages/incomplete').mkdir(parents=True)
    (root/'python/package.py').write_text('{}')
    report = inspect(PROJECT/'project/host/bootstrap-profile.py', root)
    python = next(i for i in report['items'] if i['project'] == 'python')
    assert python['package_metadata_present'] and python['recipe_gap']
    assert python['stages'][0]['missing_files']
