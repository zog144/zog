from pathlib import Path
import tempfile
from zog.image_build.stages import stage_recipes
from zog.image_build.metadata import load_packages
from zog.image_build.licensing import validate


def test_trust_recipe_pins_all_inputs_and_no_patches(tmp_path):
    root=Path(__file__).parents[1]/'project'
    stage_recipes(root/'bootstrap/host-trust.py',root/'package',tmp_path/'recipes')
    p=load_packages(tmp_path/'recipes')['ca-certificates-final']
    assert len(p.sources)==4 and all(not s['archive'] for s in p.sources)
    assert len(p.source_provenance['sources'])==4
    assert p.integration['patches_complete'] and p.integration['patches']==[]
    assert len(p.licensing['evidence'])==2
    assert '-n -f' in p.steps['build'][0][-1]
    assert 'SERVER_AUTH:TRUSTED_DELEGATOR' in p.steps['build'][0][-1]
