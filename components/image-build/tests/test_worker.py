import pytest
from zog.image_build import worker

@pytest.mark.parametrize("name", worker.WORKERS)
def test_worker_help_uses_maintained_module_without_launch(name, capsys):
    with pytest.raises(SystemExit) as error:
        worker.main([name, "--help"])
    assert error.value.code == 0
    assert "--project" in capsys.readouterr().out

def test_unknown_worker_refused():
    with pytest.raises(SystemExit) as error:
        worker.main(["historical-private-driver"])
    assert error.value.code == 2
