# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'architecture': 'x86_64',
 'lfs_edition': '13.1-systemd',
 'stages': [{'id': 'tcl-final', 'project': 'tcl', 'recipe': 'tcl/stages/final', 'stage': 'final'},
            {'id': 'expect-final',
             'project': 'expect',
             'recipe': 'expect/stages/final',
             'stage': 'final'},
            {'id': 'dejagnu-final',
             'project': 'dejagnu',
             'recipe': 'dejagnu/stages/final',
             'stage': 'final'}],
 'targets': ['dejagnu-final']}
