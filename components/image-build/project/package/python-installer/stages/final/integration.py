# Data only; parsed with ast.literal_eval.
{'project': 'python-installer',
 'stage_id': 'final',
 'base_contract': 'Accepted CPython 3.15 self-hosted root with OpenSSL, SQLite '
                  'and libffi development files.',
 'python_distribution': 'installer',
 'version': '1.0.1',
 'build_system': {'build-backend': 'flit_core.buildapi',
                  'requires': ['flit_core<4,>=3.11']},
 'runtime_requirements': [],
 'patches': [],
 'patches_complete': True,
 'test_scope': 'Wheel integrity, isolated installed imports and targeted '
               'behavior; complete upstream optional test suites are not run '
               'in this stage.',
 'source_omissions': {'reason': 'Linux-only target; do not install upstream '
                                'precompiled Windows launchers. Source archive '
                                'retained unchanged.',
                      'files': [{'path': 'installer-1.0.1/src/installer/_scripts/t32.exe',
                                 'sha256': '6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/t64-arm.exe',
                                 'sha256': 'ebc4c06b7d95e74e315419ee7e88e1d0f71e9e9477538c00a93a9ff8c66a6cfc'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/t64.exe',
                                 'sha256': '81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/t_arm.exe',
                                 'sha256': '62aee48069f0715f96da0dbe35eab7868d5cb149f62133141ab0e126d62b9cfe'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/w32.exe',
                                 'sha256': '47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/w64-arm.exe',
                                 'sha256': 'c5dc9884a8f458371550e09bd396e5418bf375820a31b9899f6499bf391c7b2e'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/w64.exe',
                                 'sha256': '7a319ffaba23a017d7b1e18ba726ba6c54c53d6446db55f92af53c279894f8ad'},
                                {'path': 'installer-1.0.1/src/installer/_scripts/w_arm.exe',
                                 'sha256': '091feafac1542754885b1b2bc57bf8a66e89351e6aa2c05ebf053fd7b66a2aba'}]}}
