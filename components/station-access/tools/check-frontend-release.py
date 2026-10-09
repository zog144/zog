"""Verify the complete shipped asset inventory and exact retained notice bytes."""
import hashlib
import json
from pathlib import Path
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--frontend',type=Path,default=Path(__file__).resolve().parents[1]/'frontend')
parser.add_argument('--dist',type=Path)
args=parser.parse_args()
root=args.frontend.resolve()
dist=args.dist.resolve() if args.dist else root/'dist'
data=json.loads((dist/'frontend-build.json').read_text())
assert data['schema']==2 and data['mode']==data['node_env']=='production'
for relative,expected in data['sources'].items():assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==expected,relative
for relative,expected in data['outputs'].items():assert hashlib.sha256((dist/relative).read_bytes()).hexdigest()==expected,relative
assert {str(p.relative_to(dist)) for p in dist.rglob('*') if p.is_file()}==set(data['outputs'])|{'frontend-build.json'},'Uninventoried output; rebuild with explicit license coverage'
html=(dist/'index.html').read_text();assert 'rel="license" href="/'+data['licenses']+'"' in html
for path in (dist/'assets').glob('*.js'):
    source=path.read_text()
    for marker in ('react.development.js','react-dom-client.development.js','jsx-dev-runtime.development.js','/src/main.tsx','@vite/client'):assert marker not in source,marker
notices=(dist/data['licenses']).read_bytes()
assert notices.startswith(b'===== Zog / station-access original material =====\n')
assert notices.startswith(b'===== Zog / station-access original material =====\n'+(root.parent/'LICENSE').read_bytes()+b'\n')
evidence=json.loads((root/'license-evidence.json').read_text())['packages']
for dep in data['dependencies']:
    reviewed=evidence[dep['name']+'@'+dep['version']]
    assert reviewed['status']=='reviewed' and dep['status']=='reviewed'
    for field in ('integrity','tarball','published_files_sha256','reviewed_terms','declared_license'):assert dep[field]==reviewed[field],field
    section=('===== '+dep['name']+' '+dep['version']+' =====\n').encode()
    offset=notices.index(section)+len(section)
    for notice in dep['notices']:
        match=next(item for item in reviewed['notices'] if item['path']==notice['path'])
        assert notice['sha256']==match['sha256']
        marker=('----- Upstream '+notice['path']+' (verbatim) -----\n').encode()
        offset=notices.index(marker,offset)+len(marker)
        text=notices[offset:offset+notice['bytes']]
        assert hashlib.sha256(text).hexdigest()==notice['sha256'],dep['name']+'/'+notice['path']
        offset+=notice['bytes']
for category in ('public_assets','fonts','images','workers'):assert data['coverage'][category]==[],category+' needs explicit reviewed coverage'
print('Production source/output hashes, complete asset inventory and exact retained upstream notice bytes verified.')
print('Reviewed output packages:',', '.join(p['name']+' '+p['version'] for p in data['dependencies']))
