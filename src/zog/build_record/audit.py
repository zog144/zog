"""Offline checks against independently supplied generation expectations."""
from pathlib import Path
from .graph import inspect, verify_artifacts
from .model import MAX_RECORDS, canonical, digest, fields, require, strings, text


def audit_generation(bundle, expected, *, paths=None):
    """Bind one export to an owner-selected root, subject and installed package set.

    Expectations must come from the trusted owner publication, not this bundle.
    This checks declared metadata and optionally explicit artifact paths. It does
    not authenticate the owner or inspect any controller, journal or rootfs tree.
    """
    fields(expected, 'schema_version record generation_id packages')
    require(type(expected['schema_version']) is int and expected['schema_version'] == 1,
            'unsupported generation expectation schema')
    digest(expected['record'])
    text(expected['generation_id'])
    strings(expected['packages'])
    require(len(expected['packages']) <= MAX_RECORDS, 'expected package count limit exceeded')
    canonical(expected)  # Reject unsupported Unicode and other nonportable values.
    if paths is not None:
        require(type(paths) is dict, 'artifact mapping must be a dictionary')
        for key, value in paths.items():
            digest(key)
            require(isinstance(value, (str, Path)), 'artifact mapping must contain local paths')
    report = inspect(bundle) if paths is None else verify_artifacts(bundle, paths)
    require(len(bundle['roots']) == 1, 'generation audit requires one root')
    root = bundle['records'].get(bundle['roots'][0])
    require(root is None or root['kind'] == 'generation', 'audit root must be a generation')
    subject = report['subjects'][0]
    packages = subject.get('packages', [])
    observed = sorted(p['package'] for p in packages if p['package'] is not None)
    unresolved = sorted(p['output'] for p in packages if p['package'] is None)
    wanted = sorted(expected['packages'])
    names_known = root is not None and not unresolved
    checks = {
        'record': 'matched' if bundle['roots'] == [expected['record']] else 'mismatch',
        'generation_id': ('unavailable' if root is None else
                          'matched' if subject['generation_id'] == expected['generation_id'] else 'mismatch'),
        'packages': ('unavailable' if not names_known else 'matched' if observed == wanted else 'mismatch'),
        'references': 'incomplete' if report['missing_records'] else 'complete',
    }
    matches = all(checks[k] == 'matched' for k in ('record', 'generation_id', 'packages'))
    verified = paths is None or all(x['status'] == 'verified' for x in report['artifact_verification'])
    return {
        'schema_version': 1,
        'scope': 'metadata' if paths is None else 'metadata-and-artifact-bytes',
        'expected': {**expected, 'packages': wanted},
        'checks': checks,
        'matches_expected_generation': matches,
        'passed': matches and report['complete'] and verified,
        'packages': {
            'observed': observed,
            'missing': sorted(set(wanted) - set(observed)) if names_known else None,
            'unexpected': sorted(set(observed) - set(wanted)),
            'unresolved_outputs': unresolved,
            'legacy': sorted(p['package'] for p in packages
                             if p['package'] is not None and p['result'] is None),
        },
        'inspection': report,
    }
