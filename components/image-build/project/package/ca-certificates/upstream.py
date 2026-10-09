{'schema': 1,
 'version': '2026-10-01',
 'homepage': 'https://www.mozilla.org/projects/security/certs/',
 'repository_url': 'https://github.com/nss-dev/nss',
 'upstream_revision': '8571d2bf95b5003535a7ecf6b1e27ef0102aaeeb',
 'conversion_repository': 'https://github.com/curl/curl',
 'conversion_revision': '39ad9b0771708c5aff20663a7ef3704bc55510d7',
 'reference': 'https://curl.se/docs/mk-ca-bundle.html',
 'notes': ['Pinned NSS source and curl converter as of 2026-10-01; no network '
           'during conversion.',
           'PEM does not carry all browser-specific constraints; TLS server '
           'roots only.',
           'Converter evaluates certificate expiry at build time; byte '
           'reproducibility is not claimed.'],
 'release_url': 'https://raw.githubusercontent.com/nss-dev/nss/8571d2bf95b5003535a7ecf6b1e27ef0102aaeeb/lib/ckfw/builtins/certdata.txt',
 'sha256': 'beb7e6dfe6499926e52c075c27bcfbe4c957f8609c575b3860273ae2806f63eb'}
