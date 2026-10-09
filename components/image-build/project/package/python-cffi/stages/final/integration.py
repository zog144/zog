# Data only; parsed with ast.literal_eval.
{'project': 'python-cffi',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'cffi',
 'version': '2.1.1',
 'build_system': {'requires': ['setuptools >= 77.0.3'], 'build-backend': 'setuptools.build_meta'},
 'runtime_requirements': ['pycparser; implementation_name != "PyPy"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
