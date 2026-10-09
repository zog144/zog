"""Test-only WSGI mirror boundary. No archive storage or live mirror integration."""
from .archive import verify


def application(public_keys, issuer, audience):
    def serve(environ, start_response):
        # Route determines required operation/collection, never token/client parameters.
        routes={
            ('GET','/collections/sources/archives/example.tar.xz'):('download','sources'),
            ('GET','/collections/sources/'):('list','sources'),
            ('GET','/collections/root-filesystems/archives/example.tar.xz'):('download','root-filesystems'),
        }
        route=routes.get((environ.get('REQUEST_METHOD'),environ.get('PATH_INFO')))
        authorization=environ.get('HTTP_AUTHORIZATION','')
        try:
            if route is None or environ.get('QUERY_STRING') or not authorization.startswith('Bearer '):raise PermissionError()
            verify(authorization[7:],public_keys,issuer,audience,*route)
            status,body='200 OK',b'fixture download authorized (not a real archive)'
        except PermissionError:status,body='403 Forbidden',b'Archive authorization denied'
        start_response(status,[('Content-Type','application/octet-stream'),('Cache-Control','no-store')])
        return [body]
    return serve
