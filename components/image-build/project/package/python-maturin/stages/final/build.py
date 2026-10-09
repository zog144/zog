# Data only; parsed with ast.literal_eval.
{'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              "python3 - <<'ZOG_VENDOR'\n"
              'import pathlib,hashlib,tomllib,json\n'
              'root=pathlib.Path.cwd()\n'
              "src=root/'upstream/maturin-1.15.0'\n"
              "lock=(src/'Cargo.lock').read_bytes()\n"
              'assert '
              "hashlib.sha256(lock).hexdigest()=='55cd5302953baf66ef08c5552c2294944dfe65251bfa51370be83370848c6f56'\n"
              "vendor=root/'vendor';vendor.mkdir()\n"
              "for row in tomllib.loads(lock.decode())['package']:\n"
              " if 'source' not in row:continue\n"
              " assert row['source']=='registry+https://github.com/rust-lang/crates.io-index'\n"
              " stem=row['name']+'-'+row['version'];crate=root/'crates'/stem/stem\n"
              ' assert crate.is_dir()\n'
              ' files={str(p.relative_to(crate)):hashlib.sha256(p.read_bytes()).hexdigest() for p '
              "in sorted(crate.rglob('*')) if p.is_file() and p.name!='.cargo-checksum.json'}\n"
              ' '
              "(crate/'.cargo-checksum.json').write_text(json.dumps({'package':row['checksum'],'files':files},sort_keys=True))\n"
              ' (vendor/stem).symlink_to(crate,target_is_directory=True)\n'
              "(src/'.cargo').mkdir(exist_ok=True)\n"
              "(src/'.cargo/config.toml').write_text('[source.crates-io]\\nreplace-with = "
              '"zog-vendor"\\n[source.zog-vendor]\\ndirectory = '
              '"/image-build/source/vendor"\\n[net]\\noffline = true\\n\')\n'
              "print('ZOG_CARGO_VENDOR',len(list(vendor.iterdir())))\n"
              'ZOG_VENDOR\n']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/maturin-1.15.0\n'
            'cargo build --release --frozen --no-default-features --bin maturin\n'
            './target/release/maturin build --release --frozen --no-default-features --bindings '
            'bin --compatibility linux --skip-auditwheel --out dist\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/maturin-1.15.0\n'
           './target/release/maturin --version\n'
           "python3 - <<'ZOG_WHEEL'\n"
           'import pathlib,zipfile,email\n'
           "wheels=list(pathlib.Path('dist').glob('*.whl'));assert len(wheels)==1\n"
           'with zipfile.ZipFile(wheels[0]) as z:\n'
           ' assert z.testzip() is None\n'
           ' names=z.namelist()\n'
           " assert all(not n.startswith('/') and '..' not in pathlib.PurePosixPath(n).parts for n "
           'in names)\n'
           ' metadata=email.message_from_bytes(z.read(next(n for n in names if '
           "n.endswith('.dist-info/METADATA'))))\n"
           " assert metadata['Name']=='maturin' and metadata['Version']=='1.15.0'\n"
           " assert 'maturin/__init__.py' in names\n"
           " assert any(n.endswith('.data/scripts/maturin') for n in names)\n"
           " print('ZOG_MATURIN_SOURCE_WHEEL_VERIFIED')\n"
           'ZOG_WHEEL\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/maturin-1.15.0\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n']],
 'environment': {'CARGO_NET_OFFLINE': 'true',
                 'CARGO_BUILD_JOBS': '6',
                 'MATURIN_NO_INSTALL_RUST': '1',
                 'PIP_NO_INDEX': '1',
                 'PYTHONNOUSERSITE': '1'}}
