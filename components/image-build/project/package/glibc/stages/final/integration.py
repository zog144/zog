# Data only; parsed with ast.literal_eval.
{'lfs_edition': '13.1-systemd',
 'project': 'glibc',
 'purpose': 'final-self-hosting-first-package',
 'self_hosted': False,
 'stage_id': 'final',
 'test_fixtures': {'schema': 1,
                   'execution_user_id': 21001,
                   'execution_group_id': 21001,
                   'thread_count_maximum': 2048,
                   'files': {'etc/passwd': 'root:x:0:0:Root:/root:/bin/bash\n'
                                           'build-user:x:21001:21001:Build user:/tmp:/bin/bash\n'
                                           'nobody:x:65534:65534:Nobody:/:/bin/false\n',
                             'etc/group': 'root:x:0:\nbuild-user:x:21001:\nnogroup:x:65534:\n',
                             'etc/nsswitch.conf': 'passwd: files\n'
                                                  'group: files\n'
                                                  'shadow: files\n'
                                                  'hosts: files dns\n'
                                                  'networks: files\n'
                                                  'services: files\n'
                                                  'protocols: files\n'
                                                  'rpc: files\n'},
                   'device_profile': 'private-null-permission-test',
                   'cache_command': ['build/elf/ldconfig',
                                     '-X',
                                     '-i',
                                     '-C',
                                     '/image-build/output/generated-ld.so.cache',
                                     '/usr/lib'],
                   'cache_artifact': 'generated-ld.so.cache',
                   'cache_destination': 'etc/ld.so.cache'}}
