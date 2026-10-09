"""Recorded final compiler transition, with test gates and detached stage resume."""
import argparse
import fcntl
import json
import logging
import platform
import shutil
from pathlib import Path
from .configuration import configured_runner
from .developer.seed_build import verify
from .engine import ImageBuild, read_selection
from .errors import ImageBuildError
from .filesystem import inventory, merge, write_json, discard_staging
from .glibc_final import wait_for
from .info_index import POLICY
from .metadata import identity
from .native import pipeline, remove_owned
from .stages import stage_recipes, recorded_root
from .local_network import FILES as NETWORK_FILES, install as install_network
from .compiler_environment import account_files, install_accounts, GENERATE_LOCALE, ACCOUNT_PREFLIGHT

PREFLIGHT = r'''set -eu
test "$(id -u)" != 0
test ! -e /tools; test ! -e /sysroot
for program in gcc g++ ld as make bison m4 perl python3 makeinfo patch; do command -v "$program"; done
test -f /usr/include/zlib.h; test -e /usr/lib/libz.so
python3 - <<'CHECK'
import os,pty,socket
addresses=socket.getaddrinfo('localhost',None,socket.AF_INET,socket.SOCK_STREAM)
assert addresses and all(item[4][0]=='127.0.0.1' for item in addresses)
with socket.socket() as server:
 server.settimeout(5);server.bind(('127.0.0.1',0));server.listen(1)
 with socket.create_connection(('localhost',server.getsockname()[1]),timeout=5) as client:
  connection,_=server.accept()
  with connection:
   connection.settimeout(5);client.sendall(b'local-test')
   assert connection.recv(64)==b'local-test'
   connection.sendall(b'passed');assert client.recv(64)==b'passed'
print('Localhost resolution and loopback round trip passed')
master,slave=os.openpty()
os.write(slave,b'Zog PTY works\n')
assert b'Zog PTY works' in os.read(master,1024)
os.close(master);os.close(slave)
assert pty.spawn(['/bin/echo','Compiler test PTY passed']) == 0
CHECK
printf 'Final compiler environment preflight passed\n'
'''
PREFLIGHT = PREFLIGHT.replace("import os,pty,socket\n", "import os,pty,socket\n" + ACCOUNT_PREFLIGHT)
ACCEPTANCE = r'''set -eu
test ! -e /tools; test ! -e /sysroot
test -z "$(gcc -print-sysroot)"
test "$(gcc -dumpfullversion)" = 16.2.0
ld --version | head -1 | grep -F '2.47'
if touch /usr/forbidden-write 2>/dev/null; then exit 1; fi
cat > probe.c <<'EOF'
#include <stdio.h>
#include <string.h>
#include <gnu/libc-version.h>
int main(void){puts(gnu_get_libc_version());return strcmp(gnu_get_libc_version(),"2.44")!=0;}
EOF
cc -v probe.c -Wl,--verbose -o /image-build/output/c-probe > /image-build/output/link.txt 2>&1
/image-build/output/c-probe
cat > probe.cc <<'EOF'
#include <thread>
#include <stdexcept>
#include <iostream>
int main(){int n=0;std::thread t([&]{n=42;});t.join();try{throw std::runtime_error("exception works");}catch(const std::exception& e){std::cout<<e.what()<<"\n";}return n!=42;}
EOF
g++ -pthread -flto probe.cc -o /image-build/output/cxx-probe
/image-build/output/cxx-probe
readelf -l /image-build/output/c-probe > /image-build/output/interpreter.txt
grep -F '/lib64/ld-linux-x86-64.so.2' /image-build/output/interpreter.txt
readelf -d /image-build/output/cxx-probe > /image-build/output/dynamic.txt
if grep -E '(RPATH|RUNPATH)' /image-build/output/dynamic.txt; then exit 1; fi
gcc -print-search-dirs > /image-build/output/search.txt
if grep -E '/(tools|sysroot|opt|root|image-build)/' /image-build/output/search.txt; then exit 1; fi
grep -E '/usr/lib/.*/?S?crt1.o|/usr/lib/S?crt1.o' /image-build/output/link.txt
grep -F '/usr/include' /image-build/output/link.txt
/lib64/ld-linux-x86-64.so.2 --list /image-build/output/cxx-probe
printf 'Final C/C++/libc, threads, exceptions and LTO acceptance passed\n' > /image-build/output/acceptance.txt
'''


def replacement_records(path):
    record = json.loads(Path(path).read_text())
    if identity({'inputs': record['inputs'], 'outputs': record['outputs']}) != record['identity']:
        raise ImageBuildError('old package ownership identity changed')
    if not record['outputs'] or any(not r['path'].startswith('sysroot/') and r['path'] != 'sysroot' for r in record['outputs']):
        raise ImageBuildError('unexpected temporary compiler ownership prefix')
    return record


def assemble(root, base, additions, replacements=()):
    """Only verified old package ownership can authorize ordinary-file replacement."""
    shutil.copytree(base, root, symlinks=True)
    for record in replacements:
        remove_owned(root, record['outputs'])
    for addition in additions:
        merge(addition, root, preserve_existing_directories=True, compose_info=True)


def successful_execution(attempt):
    result = json.loads((attempt / 'command-0.execution.json').read_text())
    if result.get('exit_code') != 0 or result.get('cleanup_complete') is not True:
        raise ImageBuildError('compiler acceptance lacks successful controller completion')
    return result


def run(project, catalogue, controller, selection, arithmetic, ownership, work):
    project, catalogue, work, ownership = (Path(p).resolve() for p in (project, catalogue, work, ownership))
    state = project / 'state'; work.mkdir(parents=True, exist_ok=True)
    with (work / 'operation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base, math = read_selection(selection), read_selection(arithmetic)
        if base.manifest['kind'] != 'native-final-libc' or base.manifest.get('source_built') is not True:
            raise ImageBuildError('final compiler requires accepted source-built final libc')
        if math.manifest['inputs'].get('toolchain') != base.generation or math.manifest['inputs'].get('targets') != ['mpc-final']:
            raise ImageBuildError('arithmetic output does not bind to this final-libc root')
        old = {name: replacement_records(ownership / (name + '-native-temporary') / 'result.json') for name in ('binutils', 'gcc')}
        plans = {}
        for stage in ('test-tools', 'binutils', 'gcc'):
            plans[stage] = stage_recipes(catalogue.parent / ('bootstrap/lfs-final-' + stage + '.py'), catalogue, work / ('recipes-' + stage))
        plans['m4'] = stage_recipes(catalogue.parent / 'bootstrap/native-m4.py', catalogue, work / 'recipes-m4')
        builder = ImageBuild(package_dir=work / 'recipes-test-tools', state_dir=state,
                             runner=configured_runner(controller, state), maximum_generations=32)
        accounts = account_files(builder.runner.execute.configuration())
        binding = {'accounts': accounts, 'locale_generation': GENERATE_LOCALE, 'base': base.generation, 'arithmetic': math.generation, 'old_packages': old,
                   'plans': plans, 'recipes': {n: inventory(work / ('recipes-' + n)) for n in plans},
                   'policy': builder._policy(), 'composition_policy': POLICY,
                   'network_configuration': NETWORK_FILES,
                   'gcc_bootstrap': 'upstream-three-stage-with-comparison',
                   'preflight': PREFLIGHT, 'acceptance': ACCEPTANCE}
        intent = work / 'intent.json'
        if intent.exists() and json.loads(intent.read_text()) != binding:
            raise ImageBuildError('recorded final compiler inputs changed')
        write_json(intent, binding)
        result_path = work / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if result['phase'] != 'complete':
                raise ImageBuildError('inspect retained compiler failure before a new operation')
            read_selection(state / 'image-build/generations' / result['generation'])
            return result
        def check(label, root, command, inputs):
            attempt = state / 'image-build/attempts' / (work.name + '-' + label)
            verified = wait_for(work, label, lambda: verify(builder, attempt, root,
                                [['/bin/bash', '-eu', '-o', 'pipefail', '-c', command]], inputs))
            return verified, successful_execution(attempt)
        def build(label, current):
            builder.package_dir = work / ('recipes-' + label)
            logging.info('Final compiler stage: %s', label)
            return wait_for(work, label, lambda: pipeline(builder, current, plans[label]['targets'], 'native-check'))
        def candidate(label, previous, additions, replacements=(), configuration=None):
            inputs = {'base': previous.generation, 'additions': [x.generation for x in additions],
                      'replaced': [r['identity'] for r in replacements], 'intent': identity(binding),
                      'network_configuration': configuration}
            def prepare(target):
                assemble(target, previous.root, [x.root for x in additions], replacements)
                if configuration is not None:
                    install_network(target, configuration)
                    install_accounts(target, accounts)
            root = recorded_root(work / (label + '-root'), inputs, prepare)
            evidence, execution = check(label, root, PREFLIGHT, inputs)
            with builder.locked():
                return builder._publish(root, {'schema': 2, 'kind': 'native-compiler-candidate',
                    'architecture': platform.machine(), 'transition': inputs, 'outputs': inventory(root),
                    'verification': identity({'result': evidence, 'execution': execution})},
                    'native-compiler-candidate', {'source_built': True, 'self_hosted': False,
                     'build_environment_complete': True, 'verification_execution': execution})
        try:
            def prepare_accounts(root):
                assemble(root, base.root, [])
                install_network(root, NETWORK_FILES)
                install_accounts(root, accounts)
            account_root = recorded_root(work / 'account-environment-root', identity(binding), prepare_accounts)
            locale_evidence, locale_execution = check('test-locales', account_root, GENERATE_LOCALE, identity(binding))
            locale_output = state / 'image-build/attempts' / (work.name + '-test-locales') / 'output'
            with builder.locked():
                locales = builder._publish(locale_output, {'schema': 2, 'kind': 'native-test-locales',
                    'base': base.generation, 'intent': identity(binding), 'outputs': inventory(locale_output),
                    'verification': identity({'result': locale_evidence, 'execution': locale_execution})},
                    'native-test-locales', {'self_hosted': False, 'source_built': True})
            base = candidate('network-environment', base, [locales], configuration=NETWORK_FILES)
            tools = build('test-tools', base)
            build_base = candidate('test-environment', base, [math, tools])
            binutils = build('binutils', build_base)
            linker_base = candidate('final-linker', build_base, [binutils], [old['binutils']])
            gcc = build('gcc', linker_base)
            compiler = candidate('final-compiler', linker_base, [gcc], [old['gcc']])
            evidence, execution = check('acceptance', compiler.root, ACCEPTANCE, {'compiler': compiler.generation})
            m4 = build('m4', compiler)
            # The built M4 binary is already run by its recipe test before installation.
            # Also execute the staged installed binary in the final compiler environment.
            probe = recorded_root(work / 'm4-probe-root', {'compiler': compiler.generation, 'm4': m4.generation},
                lambda root: (shutil.copytree(compiler.root, root, symlinks=True), shutil.copytree(m4.root, root / 'selfhost-m4', symlinks=True)))
            m4_evidence, m4_execution = check('m4-installed', probe,
                'printf "eval(6*7)\\n" | /selfhost-m4/usr/bin/m4 | grep -x 42', {'compiler': compiler.generation, 'm4': m4.generation})
            with builder.locked():
                final = builder._publish(compiler.root, {'schema': 2, 'kind': 'toolchain', 'stage': 2,
                    'architecture': platform.machine(), 'parent': compiler.generation,
                    'bootstrap': 'gcc-three-stage-comparison', 'intent': identity(binding),
                    'acceptance': identity({'compiler': evidence, 'execution': execution, 'm4': m4_evidence, 'm4_execution': m4_execution}),
                    'composition_policy': POLICY}, 'toolchain',
                    {'stage': 2, 'self_hosted': True, 'source_built': True, 'build_environment_complete': True})
                builder._activate(final, 'toolchain-active')
            result = {'phase': 'complete', 'generation': final.generation, 'root': str(final.root),
                      'self_hosted': True, 'gcc_bootstrap': 'three-stage-comparison', 'm4_generation': m4.generation}
            write_json(result_path, result)
            for label in ('account-environment', 'network-environment', 'test-environment', 'final-linker', 'final-compiler', 'm4-probe'):
                path = work / (label + '-root')
                if path.exists(): discard_staging(path)
            print(json.dumps(result), flush=True)
            return result
        except Exception as error:
            write_json(result_path, {'phase': 'failed', 'error': str(error), 'self_hosted': False})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'catalogue', 'controller', 'selection', 'arithmetic', 'ownership', 'work'):
        parser.add_argument('--' + name, required=True)
    logging.basicConfig(level=logging.INFO)
    run(**vars(parser.parse_args()))


if __name__ == '__main__':
    main()
