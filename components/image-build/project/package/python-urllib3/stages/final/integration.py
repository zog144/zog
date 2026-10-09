# Data only; parsed with ast.literal_eval.
{'project': 'python-urllib3',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite and libffi '
                  'development files.',
 'python_distribution': 'urllib3',
 'version': '2.8.0',
 'build_system': {'requires': ['hatchling>=1.27.0,<2',
                               'hatch-vcs>=0.4.0,<0.6.0',
                               'setuptools-scm>=8,<11'],
                  'build-backend': 'hatchling.build'},
 'runtime_requirements': ["brotli>=1.2.0; (platform_python_implementation == 'CPython') and extra "
                          "== 'brotli'",
                          "brotlicffi>=1.2.0.0; (platform_python_implementation != 'CPython') and "
                          "extra == 'brotli'",
                          "h2<5,>=4; extra == 'h2'",
                          "pysocks!=1.5.7,<2.0,>=1.5.6; extra == 'socks'",
                          "backports-zstd>=1.0.0; (python_version < '3.14') and extra == 'zstd'"],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted behavior; complete '
               'upstream optional test suites are not run in this stage.'}
