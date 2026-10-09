import json

import pytest
pytest.importorskip("zog.build_record")


def test_pipeline_completion_exposes_owner_selected_snapshot(tmp_path):
    from test_generation_provenance import Scenario, run

    scenario = Scenario(tmp_path)
    result = run(scenario)
    receipt = scenario.builder.selected_observation_snapshot(result.generation)
    pipeline = json.loads(scenario.pipeline().read_text())
    assert pipeline["status"] == "complete"
    assert pipeline["generation"] == result.generation
    assert pipeline["observation_snapshot"] == receipt["snapshot"]
