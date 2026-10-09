# Reviewed test-only fixtures. Parsed with ast.literal_eval, never imported.
{
 'schema': 1,
 'execution_user_id': 21001,
 'execution_group_id': 21001,
 'thread_count_maximum': 2048,
 'parallel_make_jobs': 1,
 'files': {
  'etc/passwd': 'root:x:0:0:Root:/root:/bin/bash\nbuild-user:x:21001:21001:Build user:/tmp:/bin/bash\nnobody:x:65534:65534:Nobody:/:/bin/false\n',
  'etc/group': 'root:x:0:\nbuild-user:x:21001:\nnogroup:x:65534:\n',
  'etc/nsswitch.conf': 'passwd: files\ngroup: files\nshadow: files\nhosts: files dns\nnetworks: files\nservices: files\nprotocols: files\nrpc: files\n',
 },
 'failed_tests': ['elf/tst-rtld-dash-dash','elf/tst-rtld-does-not-exist','io/tst-fchmod-errors','nptl/tst-bug24963','nss/bug17079','nss/testgrp','nss/tst-getpw','nss/tst-nss-test_errno','posix/globtest','stdlib/test-at_quick_exit-race','stdlib/test-atexit-race','stdlib/test-on_exit-race'],
}
