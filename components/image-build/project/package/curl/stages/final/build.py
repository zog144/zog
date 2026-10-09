# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/curl-8.22.0\n'
                './configure --prefix=/usr --disable-static --with-openssl '
                '--with-ca-bundle=/etc/ssl/cert.pem --without-libpsl --without-libidn2 '
                '--without-libssh2 --without-nghttp2 --without-nghttp3 --without-ngtcp2 '
                '--disable-ldap --disable-ldaps']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/curl-8.22.0\nmake -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/curl-8.22.0\n'
           './src/curl --version\n'
           "printf 'zog-curl-file-probe\\n' > zog-probe.txt\n"
           './src/curl --fail --silent "file://$PWD/zog-probe.txt" > zog-readback.txt\n'
           'cmp zog-probe.txt zog-readback.txt\n'
           "cat > zog-api.c <<'EOF'\n"
           '#include <curl/curl.h>\n'
           'int main(void) { const curl_version_info_data *v=curl_version_info(CURLVERSION_NOW); '
           'return !(v && (v->features & CURL_VERSION_SSL)); }\n'
           'EOF\n'
           'gcc -Iinclude zog-api.c -Llib/.libs -Wl,-rpath,"$PWD/lib/.libs" -lcurl -o zog-api\n'
           './zog-api\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/curl-8.22.0\nmake DESTDIR="$DESTDIR" install']],
 'environment': {}}
