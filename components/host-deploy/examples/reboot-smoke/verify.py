import json,os,pathlib,subprocess
p=pathlib.Path(os.environ['HOST_DEPLOY_STATE_DIRECTORY'])
before=json.loads((p/'prepared.json').read_text())
boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert boot!=before['boot_id']
assert boot==os.environ['HOST_DEPLOY_AFTER_BOOT_ID']
assert before['boot_id']==os.environ['HOST_DEPLOY_BEFORE_BOOT_ID']
assert before['preparation_count']==1
assert not (p/'verified.json').exists(), 'verification was repeated'
unit=subprocess.run(['systemctl','show',before['unit']+'.service','--property=LoadState','--value'],capture_output=True,text=True)
assert unit.stdout.strip()=='not-found',unit.stdout
with (p/'verified.json').open('w') as f:
 json.dump({'boot_id':boot,'transient_unit_load_state':unit.stdout.strip(),'verification_count':1},f)
 f.flush(); os.fsync(f.fileno())
print('Changed boot, preserved checkpoint, transient witness gone',flush=True)
