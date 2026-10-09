# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'version': '15.3.0',
 'upstream_revision': '4db0e8df15bef836558857c291c323add11d035c',
 'upstream_tag': 'releases/gcc-15.3.0',
 'source_sha256': 'fa59c1beef8995f27c4d71c1df227587189315d3e6faff1bb4306e61b0c530eb',
 'reason': 'Temporary fallback for GCC PR121298, reproduced on 16.2.0. GCC 15.3 retains '
           'pre-regression reassociation behavior.',
 'bug': 'https://gcc.gnu.org/bugzilla/show_bug.cgi?id=121298',
 'regression_commit': 'e8a51144c02e1cf210db5763e435802ac6fa6ad9',
 'status': 'candidate-awaiting-bootstrap-and-tests',
 'resume_tracking_when': 'New upstream candidate passes the byte-swap regression cases and normal '
                         'compiler acceptance.',
 'policy': 'No locally maintained optimizer patch. Record every candidate revision and source '
           'hash.',
 'test_policy': 'Compile-time checking enabled; neutral test board removes default PIE/SSP only '
                'for tests. Installed compiler retains default PIE/SSP.',
 'github_secondary_mirror': 'https://github.com/gcc-mirror/gcc/tree/4db0e8df15bef836558857c291c323add11d035c'}
