"""Inside box-control: diagnostic evidence, never compiler acceptance."""
import json,re,shlex,socket,subprocess
from pathlib import Path
out=Path('/image-build/output');evidence=[]
for service in ('http','ftp','telnet','smtp'):
    addresses=socket.getaddrinfo('localhost',service,type=socket.SOCK_STREAM)
    assert addresses
    print('FIXTURE PASS',service,addresses,flush=True)
build=Path('/image-build/source/build')
for suite,log in [('gcc',build/'gcc/testsuite/gcc/gcc.log'),('g++',build/'gcc/testsuite/g++/g++.log')]:
    lines=log.read_text(errors='replace').splitlines()
    failed={l.split()[1] for l in lines if l.startswith(('FAIL:','XPASS:'))};selected={}
    for line in lines:
        if not line.startswith('Executing on host: '):continue
        argv=shlex.split(re.sub(r'\s+\(timeout = \d+\)$','',line[len('Executing on host: '):]))
        for name in failed:
            if name not in selected and any(a.endswith('/'+name) for a in argv) and '-o' in argv:selected[name]=argv
    for number,(name,argv) in enumerate(sorted(selected.items())):
        variants={'default':[],'no-pie':['-fno-pie','-no-pie'],'no-ssp':['-fno-stack-protector'],'neutral':['-fno-pie','-no-pie','-fno-stack-protector']}
        if '/plugin/' in name:variants={'default':[],'checking':['-fchecking=2']}
        results={}
        for mode,flags in variants.items():
            folder=out/suite/str(number)/mode;folder.mkdir(parents=True,exist_ok=True)
            command=list(argv);pos=command.index('-o')+1;target=folder/Path(command[pos]).name;command[pos]=str(target);command+=flags
            command=[('-fplugin='+str(log.parent/a.split('=',1)[1])) if a.startswith('-fplugin=./') else a for a in command]
            r=subprocess.run(command,cwd=folder,capture_output=True,text=True,errors='replace',timeout=300)
            (folder/'stderr.txt').write_text(r.stderr);(folder/'stdout.txt').write_text(r.stdout)
            results[mode]={'command':command,'exit_code':r.returncode,'stderr':r.stderr,'assembly':target.read_text(errors='replace') if '-S' in command and target.exists() else None}
            print('DIAGNOSTIC',name,mode,'exit',r.returncode,flush=True)
        evidence.append({'test':name,'suite':suite,'variants':results})
        (out/'diagnostics.json').write_text(json.dumps({'acceptance':False,'tests':evidence},indent=2)+'\n')
print('Diagnostics complete; original suite remains failed. LTO links and upstream resolver rerun remain required.',flush=True)
