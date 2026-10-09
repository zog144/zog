# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'sqlite',
 'version': '3.54.0@9696acb0c77f1c1a7a400446686debc1312c94bc',
 'source': {'url': 'https://sqlite.org/src/tarball/sqlite.tar.gz?r=99aab2c99220a3814124a57653e6627aa91c24459bf4eb87e69c9ed0b3378a0c',
            'sha256': '7aac321c36a6e1ca2e214d14fe8f7a6b1337cbb3bcbac4c346518546e4cb910c'},
 'status': 'declared',
 'expression': 'LicenseRef-SQLite-Public-Domain',
 'scope': 'Primary upstream terms; build support and bundled components retain their own terms.',
 'evidence': [{'path': 'sqlite/LICENSE.md',
               'sha256': 'ee6af51062b30d532991face5164136ae6f84e265ecf8abe89dc69dac45ca1e7',
               'source_sha256': '7aac321c36a6e1ca2e214d14fe8f7a6b1337cbb3bcbac4c346518546e4cb910c'},
              {'path': 'sqlite/autosetup/LICENSE',
               'sha256': '679b9208e67df09977456d1d2ae4d885b9badf02c47b45a28cf95ee27c14cb18',
               'source_sha256': '7aac321c36a6e1ca2e214d14fe8f7a6b1337cbb3bcbac4c346518546e4cb910c'}],
 'components': [{'scope': 'Bundled build/test components and third-party inputs',
                 'expression': None,
                 'status': 'unresolved',
                 'notes': 'Full distribution review pending; SQLite autosetup terms retained '
                          'separately, readline is a separately built dependency.'}],
 'patches': [],
 'notes': ['Exact October 1 upstream snapshot, recorded October 3. No downstream source patches '
           'applied.',
           'Declaration is not full public-release licensing acceptance.']}
