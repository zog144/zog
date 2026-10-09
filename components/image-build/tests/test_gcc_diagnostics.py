import pytest
from jobs.gcc_diagnostics import run

def test_reject_work_outside_controller_attempts_before_mutation(tmp_path):
    with pytest.raises(ValueError, match='beneath'):
        run(tmp_path, tmp_path/'socket', 'unused', tmp_path/'state/image-build/incorrect')
    assert not (tmp_path/'state').exists()
