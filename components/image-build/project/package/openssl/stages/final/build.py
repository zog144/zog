# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/openssl-7ef69a722c129fe446d7a1fef52ff8f12ccb010b; export CFLAGS="-O2 '
                '-g -fstack-protector-strong -D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer"; export '
                'LDFLAGS="-Wl,-z,relro,-z,now"; perl Configure linux-x86_64 --prefix=/usr '
                '--libdir=lib --openssldir=/etc/ssl shared zlib enable-ktls enable-pie '
                'enable-ec_nistp_64_gcc_128 enable-camellia enable-rfc3779 enable-buildtest-c++ '
                'no-fips no-md2 no-rc5 no-ec2m no-ssl3 no-tls1 no-tls1_1 no-weak-ssl-ciphers '
                '-DOPENSSL_TLS_SECURITY_LEVEL=2; perl configdata.pm --dump']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/openssl-7ef69a722c129fe446d7a1fef52ff8f12ccb010b; make -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/openssl-7ef69a722c129fe446d7a1fef52ff8f12ccb010b; make -j8 test']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/openssl-7ef69a722c129fe446d7a1fef52ff8f12ccb010b; make '
              'DESTDIR="$DESTDIR" install_sw install_ssldirs; rm -f "$DESTDIR/usr/lib/libssl.a" '
              '"$DESTDIR/usr/lib/libcrypto.a"; cat > "$DESTDIR/etc/ssl/openssl.cnf" '
              "<<'ZOG_CONFIG'\n"
              'openssl_conf = openssl_init\n'
              'config_diagnostics = 1\n'
              '[openssl_init]\n'
              'ssl_conf = ssl_settings\n'
              '[ssl_settings]\n'
              'system_default = tls_defaults\n'
              '[tls_defaults]\n'
              'MinProtocol = TLSv1.2\n'
              'CipherString = DEFAULT:@SECLEVEL=2\n'
              'ZOG_CONFIG\n']]}
