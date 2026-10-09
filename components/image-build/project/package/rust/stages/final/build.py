# Data only; parsed with ast.literal_eval.
{'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'test "$(uname -m)" = x86_64\n'
              'mkdir -p bootstrap\n'
              'bash seed-rustc/rustc-1.98.0-x86_64-unknown-linux-gnu/install.sh '
              '--prefix="$PWD/bootstrap" --destdir= --disable-ldconfig\n'
              'bash seed-rust-std/rust-std-1.98.0-x86_64-unknown-linux-gnu/install.sh '
              '--prefix="$PWD/bootstrap" --destdir= --disable-ldconfig\n'
              'bash seed-cargo/cargo-1.98.0-x86_64-unknown-linux-gnu/install.sh '
              '--prefix="$PWD/bootstrap" --destdir= --disable-ldconfig\n'
              'bootstrap/bin/rustc --version\n'
              'bootstrap/bin/cargo --version\n'
              'cd upstream/rustc-1.99.0-src\n'
              "cat > bootstrap.toml <<'ZOG_CONFIG'\n"
              'change-id = "ignore"\n'
              '[build]\n'
              'build = "x86_64-unknown-linux-gnu"\n'
              'host = ["x86_64-unknown-linux-gnu"]\n'
              'target = ["x86_64-unknown-linux-gnu"]\n'
              'extended = true\n'
              'tools = ["cargo", "rustdoc"]\n'
              'docs = false\n'
              'vendor = true\n'
              'locked-deps = true\n'
              'submodules = false\n'
              'jobs = 6\n'
              'rustc = "/image-build/source/bootstrap/bin/rustc"\n'
              'cargo = "/image-build/source/bootstrap/bin/cargo"\n'
              'rustdoc = "/image-build/source/bootstrap/bin/rustdoc"\n'
              '[install]\n'
              'prefix = "/usr"\n'
              'sysconfdir = "/etc"\n'
              '[llvm]\n'
              'download-ci-llvm = false\n'
              'ninja = false\n'
              'targets = "X86"\n'
              'experimental-targets = ""\n'
              'link-jobs = 1\n'
              '[rust]\n'
              'channel = "stable"\n'
              'download-rustc = false\n'
              'llvm-bitcode-linker = false\n'
              'debuginfo-level = 0\n'
              'lto = "thin"\n'
              'codegen-units = 1\n'
              'ZOG_CONFIG\n']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/rustc-1.99.0-src\n'
            'python3 x.py build --stage 2 compiler/rustc library/std src/tools/cargo '
            'src/tools/rustdoc']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/rustc-1.99.0-src\npython3 x.py test --stage 2 library/std --no-fail-fast']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/rustc-1.99.0-src\nDESTDIR="$DESTDIR" python3 x.py install']],
 'environment': {'CARGO_NET_OFFLINE': 'true',
                 'CARGO_BUILD_JOBS': '6',
                 'OPENSSL_NO_VENDOR': '1',
                 'OPENSSL_DIR': '/usr',
                 'LIBSQLITE3_SYS_USE_PKG_CONFIG': '1',
                 'CURL_SYS_USE_PKG_CONFIG': '1'}}
