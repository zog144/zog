import hashlib,json,re,ssl,time
from pathlib import Path
import requests
release=Path('/opt/zog-archive-acceptance-20260927');data=Path((release/'data-path.txt').read_text())
base='https://127.0.0.1:18443'
s=requests.Session();s.trust_env=False;s.verify='/etc/station-access/tls/registry.pem'
def get(path,headers=None):return s.get(base+path,headers=headers,timeout=30,allow_redirects=False)
results={}
r=get('/');assert r.status_code==200;results['portal']=r.status_code
asset=re.search(r'src="([^"]+\.js)"',r.text)
assert asset and get(asset.group(1)).status_code==200;results['frontend_asset']=200
assert get('/archives/').status_code==401;results['anonymous_admin_catalogue']=401
r=get('/api/session/');assert r.status_code==200 and r.json()['authenticated'] is False
login=(data/'FIRST-LOGIN.txt').read_text();password=re.search(r'^Password: (.+)$',login,re.M).group(1)
r=s.post(base+'/api/login/',json={'username':'station-admin','password':password},headers={'X-CSRFToken':s.cookies['csrftoken'],'Referer':base+'/','Origin':base},timeout=30,allow_redirects=False)
assert r.status_code==200,('login',r.status_code)
assert get('/api/session/').json()['authenticated'] is True;results['browser_login']=200
assert get('/archives/').status_code==200;results['authenticated_admin_catalogue']=200
r=get('/.well-known/zog/archive-mirror/ready');assert r.status_code==200,('ready',r.status_code);results['readiness']=r.json()
record=json.loads((release/'import-result.json').read_text())
path='/collections/root-filesystems/archives/'+record['sha256']+'.tar.xz'
assert get(path).status_code==403;results['no_token_even_with_browser_session']=403
from zog.host_identify.storage import read_credentials
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import base64
c=json.loads((data/'archive-configuration.json').read_text());k=json.loads((data/'public-keyring.json').read_text())
keys={name:Ed25519PublicKey.from_public_bytes(base64.b64decode(value)) for name,value in k['keys'].items()}
grant=read_credentials('/var/lib/host-discover/credentials/archive.json',keys,c['issuer'],c['audience'],'download','root-filesystems',c['endpoint'])
headers={'Authorization':'Bearer '+grant['token']}
assert get('/collections/sources/',headers).status_code==403;results['wrong_collection']=403
assert get('/collections/root-filesystems/',headers).status_code==200;results['authorized_catalogue']=200
h=hashlib.sha256();size=0
with s.get(base+path,headers=headers,stream=True,timeout=60,allow_redirects=False) as r:
 assert r.status_code==200;results['authenticated_download']=200
 for chunk in r.iter_content(1024*1024):h.update(chunk);size+=len(chunk)
assert h.hexdigest()==record['sha256'] and size==record['bytes']
results.update(bytes=size,sha256=h.hexdigest(),tls_verified=True,completed_at=time.time())
(release/'http-acceptance.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results))
