# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash', '-eu', '-c', 'make -C build -j4']],
 'configure': [['/bin/bash',
                '-eu',
                '-c',
                'mkdir build; cd build; echo rootsbindir=/usr/sbin > configparms; '
                '../upstream/glibc-2.44/configure --prefix=/usr --disable-werror --disable-nscd '
                'libc_cv_slibdir=/usr/lib --enable-stack-protector=strong --enable-kernel=5.10']],
 'environment': {'CONFIG_SITE': '/dev/null'},
 'install': [['/bin/bash',
              '-eu',
              '-c',
              "sed '/test-installation/s@$(PERL)@echo not running@' -i "
              'upstream/glibc-2.44/Makefile; mkdir -p "$DESTDIR/etc"; touch '
              '"$DESTDIR/etc/ld.so.conf"; make -C build DESTDIR="$DESTDIR" install; sed '
              '\'/RTLDLIST=/s@/usr@@g\' -i "$DESTDIR/usr/bin/ldd"; mkdir -p '
              '"$DESTDIR/usr/share/zog-build-evidence/glibc-final"; cp build/tests.sum '
              '"$DESTDIR/usr/share/zog-build-evidence/glibc-final/tests.sum"']],
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/glibc-2.44; patch -Np1 -i ../../patches/fhs.patch; patch -Np1 -i '
              '../../patches/upstream.patch']],
 'test': [['/bin/bash',
           '-eu',
           '-c',
           'set -eu\n'
           "python3 - <<'CLEAN'\n"
           'from pathlib import Path\n'
           'import tarfile,os,time\n'
           "b=Path('build'); "
           "evidence=Path('/image-build/output/usr/share/zog-build-evidence/glibc-final/previous-tests')\n"
           'evidence.mkdir(parents=True,exist_ok=True)\n'
           "archive=evidence/('before-clean-'+str(time.time_ns())+'.tar.gz')\n"
           "standards=['ISO','ISO11','ISO99','POSIX','POSIX2008','UNIX98','XOPEN2K','XOPEN2K8','XPG4','XPG42']\n"
           "names=['catgets/de/libc.cat','catgets/sample.SJIS.cat','catgets/test1.cat','catgets/test2.cat','timezone/testdata/posixrules']\n"
           "names += ['conform/symlist-'+prefix+s for prefix in ('','stdlibs-') for s in "
           'standards]\n'
           "files=[p for p in b.rglob('*') if p.is_file() and not p.is_symlink() and "
           "(p.name.endswith(('.out','.test-result')) or p.name in ('tests.sum','tests.log'))]\n"
           'for name in names:\n'
           ' p=b/name\n'
           ' assert p.parent.resolve().is_relative_to(b.resolve())\n'
           ' if p.exists() or p.is_symlink(): files.append(p)\n'
           "with tarfile.open(archive,'w:gz',dereference=False) as t:\n"
           ' for p in files:t.add(p,arcname=str(p),recursive=False)\n'
           "with archive.open('rb') as f:os.fsync(f.fileno())\n"
           'f=os.open(evidence,os.O_RDONLY|os.O_DIRECTORY);os.fsync(f);os.close(f)\n'
           'for name in names:(b/name).unlink(missing_ok=True)\n'
           'CLEAN\n'
           'make -C build tests-clean\n'
           'set +e\n'
           'make -C build -j1 check\n'
           'result=$?\n'
           'set -e\n'
           'if test -f build/tests.sum; then cat build/tests.sum; fi\n'
           'printf \'Glibc clean suite exit code: %s\\n\' "$result"\n'
           'exit "$result"\n']]}
