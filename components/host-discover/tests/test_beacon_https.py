import datetime
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
from cryptography.x509.oid import NameOID
from zog.host_identify import signatures
from zog.host_install.state_contract import StateError
from zog.host_discover.beacon import HTTPS
from zog.host_discover.retry import RetryableTransport


def test_real_tls_signature_ca_redirect_and_response_limits(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
    ca=cert.public_bytes(serialization.Encoding.PEM);certpath=tmp_path/'cert.pem';certpath.write_bytes(ca)
    keypath=tmp_path/'key.pem';keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    signing=ed25519.Ed25519PrivateKey.generate();requests=[];errors=[];nonces=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            try:
                body=self.rfile.read(int(self.headers['Content-Length']))
                nonce,_=signatures.verify(origin+self.path,'POST',self.headers,body,signing.public_key(),'pending')
                nonces.append(nonce)
                requests.append(self.path)
                if self.path=='/temporary' and requests.count('/temporary')==1:
                    self.send_response(503);self.end_headers();return
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location',origin+'/leaked');self.end_headers();return
                self.send_response(200);self.end_headers()
                self.wfile.write(b'x'*65537 if self.path=='/large' else b'{"status":"pending"}')
            except Exception as exc:errors.append(exc)
    server=HTTPServer(('127.0.0.1',0),Handler);origin=f'https://localhost:{server.server_port}'
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certpath,keypath);server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        transport=HTTPS()
        assert transport.post(origin+'/enrollment',{},signing,'pending',ca)=={'status':'pending'}
        for url,trust in [(origin+'/untrusted',None),(origin+'/redirect',ca),(origin+'/large',ca)]:
            with pytest.raises(StateError):transport.post(url,{},signing,'pending',trust)
        with pytest.raises(RetryableTransport):transport.post(origin+'/temporary',{},signing,'pending',ca)
        assert transport.post(origin+'/temporary',{},signing,'pending',ca)=={'status':'pending'}
        assert requests==['/enrollment','/redirect','/large','/temporary','/temporary'] and not errors
        assert len(set(nonces))==len(nonces)
    finally:server.shutdown();server.server_close();thread.join(5)
