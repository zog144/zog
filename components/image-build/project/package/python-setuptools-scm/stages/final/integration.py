# Data only; parsed with ast.literal_eval.
{'project': 'python-setuptools-scm',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'setuptools-scm',
 'version': '10.3.4',
 'build_system': {'build-backend': 'setuptools.build_meta',
                  'requires': ['setuptools>=45',
                               'vcs-versioning>=2.5.0.dev0,<3',
                               'tomli>=1; python_version < "3.11"',
                               'typing-extensions>=4.1; python_version < "3.11"']},
 'runtime_requirements': ['vcs-versioning<3,>=2.5.0.dev0',
                          'packaging>=20',
                          'setuptools',
                          'tomli>=1; python_version < "3.11"',
                          'typing-extensions>=4.1; python_version < "3.11"',
                          'rich>=13; extra == "rich"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
