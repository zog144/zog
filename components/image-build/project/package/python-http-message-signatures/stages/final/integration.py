# Data only; parsed with ast.literal_eval.
{'project': 'python-http-message-signatures',
 'stage_id': 'final',
 'base_contract': 'Accepted cryptography generation; exact canonical base outputs include CPython, '
                  'cryptography, hatchling, hatch-vcs, setuptools-scm, packaging, installer and '
                  'Requests. Backend and runtime requirements checked before building.',
 'build_requirements': ['hatchling', 'hatch-vcs', 'installer', 'packaging'],
 'runtime_requirements': ['cryptography>=36.0.2'],
 'test_requirements': ['requests'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'All 11 upstream unittest methods from pinned sdist, wheel integrity, installed '
               'Ed25519 request signatures and tamper rejection. Upstream lint/type-check targets '
               'not run; no live enrollment.'}
