# Data only; parsed with ast.literal_eval.
{'schema': 1,
 'package': 'python-http-message-signatures',
 'version': '2.0.1',
 'source': {'url': 'https://files.pythonhosted.org/packages/80/95/083707b15af3bdbb6c9e54ae7f448046f7ab55f9eaa5cccdc5dd23791d15/http_message_signatures-2.0.1.tar.gz',
            'sha256': '394545b0cc296a4fd45166f57056e7e029dcd5b91d9bf549e108c96c23aa1cba'},
 'status': 'declared',
 'expression': 'Apache-2.0 AND MIT',
 'scope': 'Version-bound upstream distribution notices; full bundled-component release review '
          'incomplete.',
 'evidence': [{'path': 'http_message_signatures-2.0.1/LICENSE',
               'sha256': '87edf00eb3adb7b328bbd302d87cf4eda0743f0bc36c60189d52c05e516a0402',
               'source_sha256': '394545b0cc296a4fd45166f57056e7e029dcd5b91d9bf549e108c96c23aa1cba'},
              {'path': 'http_message_signatures-2.0.1/NOTICE',
               'sha256': 'b9f7e7237294cde9f17fecef70e04421b692867464d5f327be04b3772d42d8cd',
               'source_sha256': '394545b0cc296a4fd45166f57056e7e029dcd5b91d9bf549e108c96c23aa1cba'},
              {'path': 'http_message_signatures-2.0.1/http_message_signatures/http_sfv/__init__.py',
               'sha256': '49b480aa7360dbd2598b40341e9483ddc7dad04d50ef4ebca9bc3564e42ad5b2',
               'source_sha256': '394545b0cc296a4fd45166f57056e7e029dcd5b91d9bf549e108c96c23aa1cba'}],
 'components': [{'scope': 'http_message_signatures/http_sfv',
                 'expression': 'MIT',
                 'status': 'declared',
                 'notes': 'Embedded Mark Nottingham Structured HTTP Field Values implementation; '
                          'notice in __init__.py.'},
                {'scope': 'Remaining source distribution',
                 'expression': 'Apache-2.0',
                 'status': 'declared',
                 'notes': 'LICENSE, NOTICE and pyproject declaration inspected; full '
                          'redistribution review remains incomplete.'}],
 'patches': [],
 'notes': ['Corrected previous MIT-only catalogue label from exact publisher LICENSE; no source or '
           'version change. Apache-2.0 primary and MIT embedded component notices hash verified.']}
