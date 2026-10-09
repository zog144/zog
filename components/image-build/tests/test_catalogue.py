import shutil
from pathlib import Path

import pytest
from zog.image_build.developer.catalogue import load_catalogue, host_plan
from zog.image_build.errors import ImageBuildError
from zog.image_build.metadata import load_package

CATALOGUE = Path(__file__).parents[1] / 'project' / 'package'


def test_catalogue_and_seed_plan():
    catalogue = load_catalogue(CATALOGUE)
    assert set(catalogue) == {p.name for p in CATALOGUE.iterdir() if p.is_dir() and not p.name.startswith('.')}
    assert {'openssl', 'sqlite', 'readline'} <= set(catalogue)
    plan = host_plan(catalogue, 'amazon-linux-2023')
    assert {'bison', 'm4', 'texinfo', 'gcc-c++', 'glibc-devel'} <= set(plan['packages'])
    assert not {'gmp-devel', 'mpfr-devel', 'libmpc-devel', 'kernel-headers'} & set(plan['packages'])
    assert catalogue['linux']['distribution']['profiles']['amazon-linux-2023']['related_packages'] == ['kernel6.18-headers']
    assert plan['required_command_aliases'][0]['argv'] == ['/usr/bin/bison', '-y']
    assert catalogue['m4']['upstream']['sha256'] is not None
    import re
    assert all(item['upstream']['sha256'] is None or re.fullmatch(r'[0-9a-f]{64}', item['upstream']['sha256']) for item in catalogue.values())
    assert {'libffi', 'expat', 'gdbm', 'pkgconf'} <= set(catalogue)


def test_unreviewed_distribution_is_not_installable():
    with pytest.raises(ImageBuildError, match='requires review'):
        host_plan(load_catalogue(CATALOGUE), 'fedora-rawhide')


def test_research_metadata_cannot_be_built():
    with pytest.raises(ImageBuildError, match='catalogue-only'):
        load_package(CATALOGUE / 'gcc')


def test_catalogue_does_not_execute_python(tmp_path):
    shutil.copytree(CATALOGUE / 'gcc', tmp_path / 'gcc')
    marker = tmp_path / 'executed'
    (tmp_path / 'gcc' / 'upstream.py').write_text(f'__import__("pathlib").Path({str(marker)!r}).touch()')
    with pytest.raises(ImageBuildError, match='invalid literal'):
        load_catalogue(tmp_path)
    assert not marker.exists()


def test_seed_mapping_must_reference_known_rpm(tmp_path):
    shutil.copytree(CATALOGUE / 'gcc', tmp_path / 'gcc')
    p = tmp_path / 'gcc' / 'distribution.py'
    p.write_text(p.read_text().replace("'seed_packages': ['gcc',", "'seed_packages': ['unknown-package',"))
    with pytest.raises(ImageBuildError, match='must have a distribution mapping'):
        load_catalogue(tmp_path)


def test_source_only_mappings_do_not_authorize_host_installation():
    catalogue = load_catalogue(CATALOGUE)
    for name in ('openssl', 'sqlite'):
        profile = catalogue[name]['distribution']['profiles']['amazon-linux-2023']
        assert profile['status'] == 'unreviewed'
        assert profile['seed_required'] is False
    plan = host_plan(catalogue, 'amazon-linux-2023')
    assert not {'openssl-devel', 'sqlite-devel'} & set(plan['packages'])
    catalogue['openssl']['distribution']['profiles']['amazon-linux-2023']['seed_required'] = True
    with pytest.raises(ImageBuildError, match='requires review'):
        host_plan(catalogue, 'amazon-linux-2023')


def test_source_only_profile_cannot_smuggle_seed_packages(tmp_path):
    shutil.copytree(CATALOGUE / 'openssl', tmp_path / 'openssl')
    p = tmp_path / 'openssl' / 'distribution.py'
    p.write_text(p.read_text().replace("'seed_packages': []", "'seed_packages': ['openssl-devel']"))
    with pytest.raises(ImageBuildError, match='source-only profile cannot request'):
        load_catalogue(tmp_path)
