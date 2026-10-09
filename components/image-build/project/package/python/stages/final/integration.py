# Data only; parsed with ast.literal_eval.
{'project': 'python',
 'stage_id': 'final',
 'base_contract': 'Accepted self-hosted toolchain with OpenSSL, SQLite, Readline, ncurses, zlib, '
                  'zstd, xz, bzip2, mpdecimal, util-linux; compiler/make/shell/test tools from '
                  'recorded base.',
 'test_fixtures': {'schema': 1,
                   'execution_user_id': 21001,
                   'execution_group_id': 21001,
                   'thread_count_maximum': 2048,
                   'device_profile': 'private-null-permission-test',
                   'files': {'etc/services': '# Deterministic offline test fixture; no services '
                                             'are started.\n'
                                             'ftp 21/tcp\n'
                                             'telnet 23/tcp\n'
                                             'smtp 25/tcp\n'
                                             'domain 53/tcp\n'
                                             'domain 53/udp\n'
                                             'http 80/tcp\n'}},
 'test_exceptions': [{'id': 'cpython-rds-fixture-peek',
                      'selector': 'test.test_socket.RDSTest.testPeek',
                      'action': 'exclude-exact-test',
                      'package_version': '3.15.0rc2',
                      'source_sha256': '8d93af5eaaaea5adfd41bd786a7ba3f03f2ad1ab57c6a65e0b963deab91d5ad7',
                      'reason': 'Shared client fixture closes the sender without receiver '
                                'acknowledgement; fresh-namespace Python/C diagnostics identify '
                                'startup and sender-lifetime behavior. Original sender-close '
                                'ordering is not accepted.',
                      'reviewed': '2026-10-04',
                      'authorization': 'User explicitly approved exceptions for all five RDSTest '
                                       'methods on 2026-10-04.',
                      'upstream_review': 'No applicable fix identified in the recorded '
                                         'investigation. Related issue 136110 concerns testPeek '
                                         'and does not establish this exact cause.',
                      'observed_kernel': '6.18.44-99.149.amzn2023.x86_64',
                      'supplemental_check': '100 rounds of all five original receiver methods with '
                                            'sender teardown held until receiver completion (500 '
                                            'checks), required when RDS is available. '
                                            'Thirty-second fatal watchdog. Original sender-close '
                                            'ordering remains unverified.',
                      'retirement': 'Reassess at each monthly Python pin and kernel change; remove '
                                    'when the unchanged case passes with an applicable upstream '
                                    'fix or corrected environment.',
                      'supersedes': ['cpython-rds-peek-136110']},
                     {'id': 'cpython-rds-fixture-select',
                      'selector': 'test.test_socket.RDSTest.testSelect',
                      'action': 'exclude-exact-test',
                      'package_version': '3.15.0rc2',
                      'source_sha256': '8d93af5eaaaea5adfd41bd786a7ba3f03f2ad1ab57c6a65e0b963deab91d5ad7',
                      'reason': 'Shared client fixture closes the sender without receiver '
                                'acknowledgement; fresh-namespace Python/C diagnostics identify '
                                'startup and sender-lifetime behavior. Original sender-close '
                                'ordering is not accepted.',
                      'reviewed': '2026-10-04',
                      'authorization': 'User explicitly approved exceptions for all five RDSTest '
                                       'methods on 2026-10-04.',
                      'upstream_review': 'No applicable fix identified in the recorded '
                                         'investigation. Related issue 136110 concerns testPeek '
                                         'and does not establish this exact cause.',
                      'observed_kernel': '6.18.44-99.149.amzn2023.x86_64',
                      'supplemental_check': '100 rounds of all five original receiver methods with '
                                            'sender teardown held until receiver completion (500 '
                                            'checks), required when RDS is available. '
                                            'Thirty-second fatal watchdog. Original sender-close '
                                            'ordering remains unverified.',
                      'retirement': 'Reassess at each monthly Python pin and kernel change; remove '
                                    'when the unchanged case passes with an applicable upstream '
                                    'fix or corrected environment.',
                      'supersedes': ['cpython-rds-select-sender-lifetime']},
                     {'id': 'cpython-rds-fixture-sendandrecv',
                      'selector': 'test.test_socket.RDSTest.testSendAndRecv',
                      'action': 'exclude-exact-test',
                      'package_version': '3.15.0rc2',
                      'source_sha256': '8d93af5eaaaea5adfd41bd786a7ba3f03f2ad1ab57c6a65e0b963deab91d5ad7',
                      'reason': 'Shared client fixture closes the sender without receiver '
                                'acknowledgement; fresh-namespace Python/C diagnostics identify '
                                'startup and sender-lifetime behavior. Original sender-close '
                                'ordering is not accepted.',
                      'reviewed': '2026-10-04',
                      'authorization': 'User explicitly approved exceptions for all five RDSTest '
                                       'methods on 2026-10-04.',
                      'upstream_review': 'No applicable fix identified in the recorded '
                                         'investigation. Related issue 136110 concerns testPeek '
                                         'and does not establish this exact cause.',
                      'observed_kernel': '6.18.44-99.149.amzn2023.x86_64',
                      'supplemental_check': '100 rounds of all five original receiver methods with '
                                            'sender teardown held until receiver completion (500 '
                                            'checks), required when RDS is available. '
                                            'Thirty-second fatal watchdog. Original sender-close '
                                            'ordering remains unverified.',
                      'retirement': 'Reassess at each monthly Python pin and kernel change; remove '
                                    'when the unchanged case passes with an applicable upstream '
                                    'fix or corrected environment.',
                      'supersedes': []},
                     {'id': 'cpython-rds-fixture-sendandrecvmsg',
                      'selector': 'test.test_socket.RDSTest.testSendAndRecvMsg',
                      'action': 'exclude-exact-test',
                      'package_version': '3.15.0rc2',
                      'source_sha256': '8d93af5eaaaea5adfd41bd786a7ba3f03f2ad1ab57c6a65e0b963deab91d5ad7',
                      'reason': 'Shared client fixture closes the sender without receiver '
                                'acknowledgement; fresh-namespace Python/C diagnostics identify '
                                'startup and sender-lifetime behavior. Original sender-close '
                                'ordering is not accepted.',
                      'reviewed': '2026-10-04',
                      'authorization': 'User explicitly approved exceptions for all five RDSTest '
                                       'methods on 2026-10-04.',
                      'upstream_review': 'No applicable fix identified in the recorded '
                                         'investigation. Related issue 136110 concerns testPeek '
                                         'and does not establish this exact cause.',
                      'observed_kernel': '6.18.44-99.149.amzn2023.x86_64',
                      'supplemental_check': '100 rounds of all five original receiver methods with '
                                            'sender teardown held until receiver completion (500 '
                                            'checks), required when RDS is available. '
                                            'Thirty-second fatal watchdog. Original sender-close '
                                            'ordering remains unverified.',
                      'retirement': 'Reassess at each monthly Python pin and kernel change; remove '
                                    'when the unchanged case passes with an applicable upstream '
                                    'fix or corrected environment.',
                      'supersedes': []},
                     {'id': 'cpython-rds-fixture-sendandrecvmulti',
                      'selector': 'test.test_socket.RDSTest.testSendAndRecvMulti',
                      'action': 'exclude-exact-test',
                      'package_version': '3.15.0rc2',
                      'source_sha256': '8d93af5eaaaea5adfd41bd786a7ba3f03f2ad1ab57c6a65e0b963deab91d5ad7',
                      'reason': 'Shared client fixture closes the sender without receiver '
                                'acknowledgement; fresh-namespace Python/C diagnostics identify '
                                'startup and sender-lifetime behavior. Original sender-close '
                                'ordering is not accepted.',
                      'reviewed': '2026-10-04',
                      'authorization': 'User explicitly approved exceptions for all five RDSTest '
                                       'methods on 2026-10-04.',
                      'upstream_review': 'No applicable fix identified in the recorded '
                                         'investigation. Related issue 136110 concerns testPeek '
                                         'and does not establish this exact cause.',
                      'observed_kernel': '6.18.44-99.149.amzn2023.x86_64',
                      'supplemental_check': '100 rounds of all five original receiver methods with '
                                            'sender teardown held until receiver completion (500 '
                                            'checks), required when RDS is available. '
                                            'Thirty-second fatal watchdog. Original sender-close '
                                            'ordering remains unverified.',
                      'retirement': 'Reassess at each monthly Python pin and kernel change; remove '
                                    'when the unchanged case passes with an applicable upstream '
                                    'fix or corrected environment.',
                      'supersedes': []}]}
