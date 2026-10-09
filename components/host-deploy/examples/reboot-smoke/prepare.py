import json,os,pathlib,subprocess
p=pathlib.Path(os.environ['HOST_DEPLOY_STATE_DIRECTORY'])
assert not (p/'prepared.json').exists(), 'preparation was repeated'
boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
unit='host-deploy-witness-'+p.parent.name
subprocess.run(['systemd-run','--quiet','--unit='+unit,'--property=Type=exec','sleep','1200'],check=True)
with (p/'prepared.json').open('w') as f:
 json.dump({'boot_id':boot,'unit':unit,'preparation_count':1,'checkpoint':'durable test data'},f)
 f.flush(); os.fsync(f.fileno())
d=os.open(p,os.O_DIRECTORY); os.fsync(d); os.close(d)
print('Prepared persistent checkpoint and transient witness',flush=True)
