"""Build and test a pinned GCC fallback inside an existing box-control build job.

This produces retained compiler/test evidence, never installation or promotion.
The caller records the source hash and launch request before dispatch.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time


def verify_summary(text):
    if not re.search(r'=== .* Summary ===', text):
        raise ValueError('missing DejaGNU summary')
    if re.search(r'^(FAIL|XPASS|UNRESOLVED|ERROR):', text, re.M):
        raise ValueError('unexpected DejaGNU result')
    counts = {}
    for label, number in re.findall(r'^# of (.+?)\s+(\d+)\s*$', text, re.M):
        counts[label] = counts.get(label, 0) + int(number)
    allowed = {'expected passes', 'expected failures', 'unsupported tests', 'untested testcases'}
    if any(n and label not in allowed for label, n in counts.items()):
        raise ValueError('unexpected DejaGNU count')
    if counts.get('expected passes', 0) < 1:
        raise ValueError('no passing tests')
    return counts


def run(version, sha256, jobs):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or jobs < 1:
        raise ValueError('invalid version/jobs')
    base = Path('/image-build/source')
    archive = base / ('gcc-' + version + '.tar.xz')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != sha256:
        raise ValueError('source hash mismatch')
    work = base / ('pin-' + version)
    out = Path('/image-build/output') / ('pin-' + version)
    work.mkdir(exist_ok=False)
    out.mkdir(exist_ok=False)
    state = {'version': version, 'source_sha256': sha256,
             'acceptance': False, 'self_hosted': False, 'steps': []}

    def save():
        tmp = out / 'progress.tmp'
        tmp.write_text(json.dumps(state, indent=2) + '\n')
        tmp.replace(out / 'progress.json')

    def command(phase, argv, cwd):
        state['status'] = phase
        save()
        print('GCC PIN START', phase, json.dumps(argv), flush=True)
        start = time.time()
        result = subprocess.run(argv, cwd=cwd)
        state['steps'].append({'phase': phase, 'command': argv,
                               'exit_code': result.returncode, 'seconds': time.time()-start})
        save()
        if result.returncode:
            raise RuntimeError(phase + ' command failed')

    try:
        state['status'] = 'extracting'
        save()
        with tarfile.open(archive) as source:
            source.extractall(work, filter='data')
        src = work / ('gcc-' + version)
        # Existing Zog library-directory policy; no optimizer bug-fix patch.
        layout = src / 'gcc/config/i386/t-linux64'
        layout.write_text(''.join(line.replace('lib64', 'lib') if 'm64=' in line else line
                                 for line in layout.read_text().splitlines(keepends=True)))
        build = work / 'build'
        build.mkdir()
        command('configure', [str(src/'configure'), '--prefix=/usr',
            '--build=x86_64-zog-linux-gnu', '--host=x86_64-zog-linux-gnu',
            '--target=x86_64-zog-linux-gnu', 'LD=ld', '--enable-languages=c,c++',
            '--enable-default-pie', '--enable-default-ssp', '--enable-host-pie',
            '--enable-targets=all', '--disable-multilib', '--enable-bootstrap',
            '--enable-checking=yes', '--disable-fixincludes', '--with-system-zlib',
            '--with-zstd', '--without-isl', '--disable-libgdiagnostics'], build)
        command('bootstrap', ['make', '-j'+str(jobs), 'bootstrap'], build)
        neutral = ' --target_board=unix/-fno-pie/-no-pie/-fno-stack-protector'
        for name in ('pr115102.c', 'xchg-4.c'):
            command(name, ['make', '-C', 'gcc', '-j1', 'check-gcc',
                          'RUNTESTFLAGS=i386.exp='+name+neutral], build)
            text = (build/'gcc/testsuite/gcc/gcc.sum').read_text()
            (out/(name+'.sum')).write_text(text)
            state['steps'][-1]['counts'] = verify_summary(text)
            save()
        state['byte_swap_gate_passed'] = True
        save()
        command('full-tests', ['make', '-k', '-j'+str(jobs), 'check'], build)
        reports = {}
        for summary in build.rglob('*.sum'):
            text = summary.read_text(errors='replace')
            if ' Summary ===' not in text:
                continue
            relative = summary.relative_to(build)
            target = out/'summaries'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            reports[str(relative)] = verify_summary(text)
        if not {'gcc.sum', 'g++.sum', 'libstdc++.sum'} <= {Path(n).name for n in reports}:
            raise ValueError('required compiler suites missing')
        state.update(status='build-and-tests-passed', suites=reports)
        save()
        print('GCC PIN: build/tests passed; installation and generation acceptance remain pending', flush=True)
    except Exception as error:
        state.update(status='failed', error=str(error))
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--jobs', type=int, default=8)
    run(**vars(parser.parse_args()))
