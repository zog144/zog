# Data only; parsed with ast.literal_eval.
{'reference': 'https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter08/bc.html',
 'source_sha256': '91eb74caed0ee6655b669711a4f350c25579778694df248e28363318e03c7fc4',
 'base_requirements': ['native C/C++ compiler', 'Make', 'shell/core utilities'],
 'verification': 'Upstream tests required; live box-control acceptance pending.',
 'adaptations': 'LFS -G bootstrap excludes tests generated using an already-installed bc. Explicit '
                'internal history avoids introducing Readline; existing upstream tests remain '
                'mandatory.'}
