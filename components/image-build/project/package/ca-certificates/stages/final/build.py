# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'perl mk-ca-bundle.pl -n -f -m -p SERVER_AUTH:TRUSTED_DELEGATOR ca-bundle.crt']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           "test $(grep -c '^-----BEGIN CERTIFICATE-----' ca-bundle.crt) -ge 100; openssl "
           'crl2pkcs7 -nocrl -certfile ca-bundle.crt -out /dev/null']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'install -Dm644 ca-bundle.crt "$DESTDIR/etc/ssl/cert.pem"; mkdir -p '
              '"$DESTDIR/etc/ssl/certs"; ln -s ../cert.pem '
              '"$DESTDIR/etc/ssl/certs/ca-certificates.crt"']]}
