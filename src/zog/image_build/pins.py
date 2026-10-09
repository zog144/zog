"""Literal monthly source locks. Normal builds never resolve a moving branch."""
from datetime import date
from pathlib import Path
import pprint

from .errors import ImageBuildError
from .metadata import identity, literal


def load(path):
    record = literal(path)
    try:
        day = date.fromisoformat(record['date'])
        if record['schema'] != 1 or day.day != 1 or not isinstance(record['packages'], dict):
            raise ValueError('invalid schema/date/packages')
        return record
    except (KeyError, TypeError, ValueError) as error:
        raise ImageBuildError('invalid monthly commit-pin.py') from error


def validate(directory, packages):
    """Require an explicit lock for every recipe before new execution."""
    record = load(Path(directory)/'commit-pin.py')
    for name, package in packages.items():
        entry = record['packages'].get(name)
        if not isinstance(entry, dict) or entry.get('sources') != list(package.sources):
            raise ImageBuildError(f'{name}: recipe sources differ from monthly pin; review both together')
    return record


def snapshot(catalogue, entries, destination, pin_date=None):
    pins = Path(catalogue).parent/'pins'
    selected = pin_date or literal(pins/'current.py')['date']
    try:
        day = date.fromisoformat(selected)
        if day.day != 1 or selected != day.isoformat():
            raise ValueError('not a monthly date')
    except (TypeError, ValueError) as error:
        raise ImageBuildError('invalid pin date') from error
    monthly = load(pins/selected/'commit-pin.py')
    if monthly['date'] != selected:
        raise ImageBuildError('pin directory/date mismatch')
    packages = {}
    for entry in entries:
        project = monthly['packages'].get(entry['project'], {})
        key = entry['recipe']
        sources = project.get('recipes', {}).get(key)
        if sources is None:
            raise ImageBuildError(f'{key}: missing reviewed monthly source pin')
        packages[entry['id']] = {'sources': sources, 'project': entry['project'], 'recipe': key}
    record = {'schema': 1, 'date': selected, 'monthly_identity': identity(monthly), 'packages': packages}
    path = Path(destination)/'commit-pin.py'
    if path.exists():
        if load(path) != record:
            raise ImageBuildError('recorded monthly pins changed; use a new operation')
    else:
        if any(Path(destination).iterdir()):
            raise ImageBuildError('legacy recipes have no monthly pins; use a new operation directory')
        path.write_text('# Literal monthly source snapshot; do not execute.\n'+pprint.pformat(record, sort_dicts=False)+'\n')
    return record
