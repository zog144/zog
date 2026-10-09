from pathlib import Path
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages, order

ROOT = Path(__file__).resolve().parents[1]/'project'

def test_library_plan_has_explicit_readline_dependency_and_monthly_pins(tmp_path):
    plan=stage_recipes(ROOT/'bootstrap/python-libraries.py',ROOT/'package',tmp_path/'recipes')
    packages=load_packages(tmp_path/'recipes')
    assert order(packages,plan['targets']) == ('openssl-final','readline-final','sqlite-final')
    assert packages['sqlite-final'].licensing['source']['sha256'] == packages['sqlite-final'].sources[0]['sha256']
    assert packages['openssl-final'].licensing['source']['sha256'] == packages['openssl-final'].sources[0]['sha256']

def test_installed_checks_cover_both_libraries_and_negative_certificate_validation():
    from zog.image_build.source_libraries import CHECK
    assert '-lssl -lcrypto -lsqlite3 -lreadline' in CHECK
    assert '-verify_hostname wrong.invalid' in CHECK
    assert 'SSL_CTX_get_min_proto_version' in CHECK
    assert 'ENABLE_SESSION' in CHECK
