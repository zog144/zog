"""Run registry tests on a file DB and station regressions on their normal isolated test DB."""
import os
import sys
import tempfile
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "src"

if len(sys.argv) == 1:
    groups = ["tests.host_registry", "tests.station_access", "tests.archive_inventory"]
    results = [subprocess.call([sys.executable, __file__, group]) for group in groups]
    sys.exit(any(results))

sys.path.insert(0, str(root))
sys.path.insert(0, str(source))
os.environ["PYTHONPATH"] = os.pathsep.join(sys.path)

with tempfile.TemporaryDirectory(prefix="host-security-tests-") as directory:
    os.environ["STATION_ACCESS_STATE_DIRECTORY"] = directory
    os.environ["DJANGO_SETTINGS_MODULE"] = "zog.station_access.project.settings"
    from django.conf import settings

    if sys.argv[1].startswith("tests.host_registry"):
        settings.DATABASES["default"]["TEST"] = {"NAME": str(Path(directory) / "test.sqlite3")}

    import django
    django.setup()
    from django.test.utils import get_runner

    failures = get_runner(settings)(verbosity=2, interactive=False).run_tests(sys.argv[1:])
    sys.exit(bool(failures))
