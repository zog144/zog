# Data only; parsed with ast.literal_eval.
{'project': 'python-requests',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'requests',
 'version': '2.34.2',
 'build_system': {'requires': ['setuptools>=61.0'], 'build-backend': 'setuptools.build_meta'},
 'runtime_requirements': ['charset_normalizer<4,>=2',
                          'idna<4,>=2.5',
                          'urllib3<3,>=1.26',
                          'certifi>=2023.5.7',
                          'PySocks!=1.5.7,>=1.5.6; extra == "socks"',
                          'chardet<8,>=3.0.2; extra == "use-chardet-on-py3"'],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
