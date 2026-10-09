# Data only; parsed with ast.literal_eval.
{'project': 'python-pathspec',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'pathspec',
 'version': '1.1.1',
 'build_system': {'build-backend': 'flit_core.buildapi', 'requires': ['flit_core >=3.2,<5']},
 'runtime_requirements': ['hyperscan >=0.7 ; extra == "hyperscan"',
                          'typing-extensions >=4 ; extra == "optional"',
                          'google-re2 >=1.1 ; extra == "re2"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
