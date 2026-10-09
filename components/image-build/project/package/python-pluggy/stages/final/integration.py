# Data only; parsed with ast.literal_eval.
{'project': 'python-pluggy',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'pluggy',
 'version': '1.6.0',
 'build_system': {'requires': ['setuptools>=65.0', 'setuptools-scm[toml]>=8.0'],
                  'build-backend': 'setuptools.build_meta'},
 'runtime_requirements': ['pre-commit; extra == "dev"',
                          'tox; extra == "dev"',
                          'pytest; extra == "testing"',
                          'pytest-benchmark; extra == "testing"',
                          'coverage; extra == "testing"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
