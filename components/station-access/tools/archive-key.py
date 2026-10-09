"""Provision separate archive access signing key; output ONLY public verification data."""
import argparse,json,sys
from pathlib import Path
from zog.host_identify.storage import load_key
from zog.host_identify.signatures import public_text
p=argparse.ArgumentParser()
p.add_argument('--directory',required=True,help='Existing mode 0700 directory owned by issuing service')
p.add_argument('--key-id',required=True)
a=p.parse_args()
key=load_key(a.directory)
print(json.dumps({'version':1,'keys':{a.key_id:public_text(key.public_key())}},indent=2))
