# Data only; read with ast.literal_eval, never import.
{'schema': 1,
 'profiles': {'amazon-linux-2023': {'status': 'repository-names-verified',
                                    'reference': 'LFS-AMAZON-LINUX-INVENTORY.json (2026-09-16)',
                                    'related_packages': ['gcc', 'gcc-c++', 'libstdc++-devel'],
                                    'seed_packages': ['gcc', 'gcc-c++', 'libstdc++-devel']},
              'fedora-rawhide': {'status': 'unreviewed',
                                 'related_packages': None,
                                 'seed_packages': None}},
 'host_minimum_version': '5.4',
 'notes': 'Related RPMs are a mapping, not an instruction to install all development packages. '
          'Seed packages are bootstrap prerequisites only.'}
