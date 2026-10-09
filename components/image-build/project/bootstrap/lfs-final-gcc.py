# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'architecture': 'x86_64',
 'lfs_edition': '13.1-systemd',
 'stages': [{'id': 'gawk-final',
             'project': 'gawk',
             'recipe': 'gawk/stages/final',
             'stage': 'final'},
            {'id': 'zstd-final',
             'project': 'zstd',
             'recipe': 'zstd/stages/final',
             'stage': 'final'},
            {'id': 'gcc-final', 'project': 'gcc', 'recipe': 'gcc/stages/final', 'stage': 'final'}],
 'targets': ['gcc-final', 'gawk-final', 'zstd-final']}
