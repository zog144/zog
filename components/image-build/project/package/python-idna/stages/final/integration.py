# Data only; parsed with ast.literal_eval.
{'project': 'python-idna',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'idna',
 'version': '3.20',
 'build_system': {'requires': ['flit_core >=3.11,<5'], 'build-backend': 'flit_core.buildapi'},
 'runtime_requirements': ['ruff >= 0.16.0 ; extra == "all"',
                          'mypy >= 1.11.2 ; extra == "all"',
                          'ty >= 0.0.37 ; extra == "all"',
                          'pytest >= 8.3.2 ; extra == "all"',
                          'hypothesis >= 6.141.1 ; extra == "all"',
                          'coverage >= 7.10.0 ; extra == "all"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
