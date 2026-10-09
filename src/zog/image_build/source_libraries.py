"""Build and verify pinned OpenSSL/SQLite on an accepted self-hosted toolchain."""
import argparse
import fcntl
import json
import platform
import shutil
from pathlib import Path
from . import ImageBuild, read_selection
from .configuration import configured_runner
from .developer.seed_build import verify
from .filesystem import inventory, merge, write_json
from .glibc_final import wait_for
from .stages import recorded_root, stage_recipes
from .final_compiler import successful_execution

CHECK = r'''set -eu
openssl version -a
openssl list -providers
if openssl list -providers | grep -q 'legacy'; then exit 1; fi
openssl list -providers -provider default -provider legacy | grep legacy
openssl req -x509 -newkey rsa:2048 -sha256 -noenc -keyout key.pem -out cert.pem -days 1 -subj /CN=localhost -addext subjectAltName=DNS:localhost
openssl verify -CAfile cert.pem -verify_hostname localhost cert.pem
if openssl verify -CAfile cert.pem -verify_hostname wrong.invalid cert.pem; then exit 1; fi
sqlite3 /image-build/output/check.db <<'SQL'
.bail on
PRAGMA journal_mode=WAL;
CREATE TABLE example(id INTEGER PRIMARY KEY, value TEXT);
BEGIN;
INSERT INTO example(value) VALUES('passed');
COMMIT;
CREATE VIRTUAL TABLE words USING fts5(value);
INSERT INTO words VALUES('compiler accepted');
SELECT count(*) FROM words WHERE words MATCH 'accepted';
CREATE VIRTUAL TABLE boxes USING rtree(id,x0,x1,y0,y1);
INSERT INTO boxes VALUES(1,0,1,0,1);
SELECT json_extract('{"result":42}', '$.result');
PRAGMA integrity_check;
SQL
test "$(sqlite3 /image-build/output/check.db 'SELECT value FROM example')" = passed
cat > library-probe.c <<'C'
#include <openssl/ssl.h>
#include <sqlite3.h>
#include <readline/history.h>
#include <stdio.h>
int main(void) {
 const char *options[]={"THREADSAFE=1","ENABLE_COLUMN_METADATA","ENABLE_FTS3","ENABLE_FTS4","ENABLE_FTS5","ENABLE_RTREE","ENABLE_SESSION","ENABLE_PREUPDATE_HOOK","ENABLE_UNLOCK_NOTIFY","ENABLE_DBSTAT_VTAB"};
 for(unsigned i=0;i<sizeof(options)/sizeof(options[0]);i++) if(!sqlite3_compileoption_used(options[i])) {fprintf(stderr,"missing %s\n",options[i]);return 1;}
 using_history(); add_history("accepted"); if(history_length!=1)return 5;
 SSL_CTX *ctx=SSL_CTX_new(TLS_method()); if(!ctx)return 2;
 if(SSL_CTX_get_security_level(ctx)<2)return 3;
 if(SSL_CTX_get_min_proto_version(ctx)<TLS1_2_VERSION)return 4;
 SSL_CTX_free(ctx);printf("OpenSSL %s; SQLite %s: installed-library checks passed\n",OpenSSL_version(OPENSSL_VERSION),sqlite3_libversion());return 0;
}
C
cc library-probe.c -o /image-build/output/library-probe -lssl -lcrypto -lsqlite3 -lreadline
/image-build/output/library-probe
'''


def run(project, catalogue, controller, selection, work, maximum_generations=32):
    project,catalogue,controller,selection,work=map(lambda p:Path(p).resolve(),(project,catalogue,controller,selection,work))
    work.mkdir(parents=True,exist_ok=True)
    with (work/'operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        base=read_selection(selection)
        if base.manifest.get('kind')!='toolchain' or not base.manifest.get('self_hosted') or base.manifest.get('stage')!=2:
            raise ValueError('Libraries require an accepted self-hosted toolchain')
        plan=stage_recipes(catalogue.parent/'bootstrap/python-libraries.py',catalogue,work/'recipes')
        builder=ImageBuild(package_dir=work/'recipes',state_dir=project/'state',runner=configured_runner(controller,project/'state'),maximum_generations=maximum_generations)
        intent={'base':base.generation,'recipes':inventory(work/'recipes'),'policy':builder._policy()}
        saved=work/'intent.json'
        if saved.exists() and json.loads(saved.read_text())!=intent:raise ValueError('Library build inputs changed')
        write_json(saved,intent)
        def build():
            matches=[]
            for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json'):
                r=json.loads(p.read_text())
                if not r.get('released') and r['operation']=='image' and r['selection']==str(base.root.parent) and r['recipes']==intent['recipes'] and r['arguments']['targets']==plan['targets']:matches.append(r['pipeline_id'])
            if len(matches)>1:raise ValueError('Ambiguous library pipeline')
            return builder.resume(matches[0]) if matches else builder.ensure(plan['targets'],toolchain=base)
        packages=wait_for(work,'libraries',build)
        root=work/'combined-root'
        def compose(destination):
            shutil.copytree(base.root,destination,symlinks=True)
            merge(packages.root,destination)
        recorded_root(root,{'base':base.generation,'packages':packages.generation},compose)
        attempt=builder.state/'image-build/attempts'/work.name
        evidence=wait_for(work,'installed-libraries',lambda:verify(builder,attempt,root,[['/bin/bash','-eu','-c',CHECK]],intent))
        execution=successful_execution(attempt)
        with builder.locked():
            accepted=builder._publish(root,{'schema':2,'kind':'toolchain','stage':2,'architecture':platform.machine(),'base':base.generation,'libraries':packages.generation,'verification':evidence},'toolchain',{'stage':2,'self_hosted':True,'source_built':True,'build_environment_complete':True,'verification_execution':execution})
        result={'phase':'complete','base':base.generation,'packages':packages.generation,'generation':accepted.generation,'root':str(accepted.root),'python_rebuild_required':True}
        write_json(work/'result.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','catalogue','controller','selection','work'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--maximum-generations',type=int,default=32)
    print(json.dumps(run(**vars(parser.parse_args()))),flush=True)

if __name__=='__main__':main()
