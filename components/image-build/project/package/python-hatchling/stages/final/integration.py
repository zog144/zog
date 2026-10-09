# Data only; parsed with ast.literal_eval.
{'project': 'python-hatchling',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'hatchling',
 'version': '1.32.4',
 'build_system': {'requires': [], 'build-backend': 'hatchling.ouroboros', 'backend-path': ['src']},
 'runtime_requirements': ['packaging>=24.2',
                          'pathspec>=0.10.1',
                          'pluggy>=1.0.0',
                          "tomli>=1.2.2; python_version < '3.11'",
                          'tomlkit>=0.11.1',
                          'trove-classifiers'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
