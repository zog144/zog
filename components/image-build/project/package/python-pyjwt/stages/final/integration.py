# Data only; parsed with ast.literal_eval.
{'project': 'python-pyjwt',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'PyJWT',
 'version': '2.15.1',
 'build_system': {'build-backend': 'setuptools.build_meta', 'requires': ['setuptools>=77.0.3']},
 'runtime_requirements': ['typing_extensions>=4.0; python_version < "3.11"',
                          'cryptography>=3.4.0; extra == "crypto"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
