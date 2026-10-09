# Data only; parsed with ast.literal_eval.
{'project': 'rust',
 'stage_id': 'final',
 'version': '1.99.0',
 'patches': [],
 'patches_complete': True,
 'base_contract': 'Accepted native GCC/Python/OpenSSL/SQLite development root.',
 'test_scope': 'Upstream stage2 standard-library tests; installed rustc/Cargo offline crate build '
               'and test; complete rustc UI and Cargo suites not claimed.',
 'bootstrap_seed': {'version': '1.98.0',
                    'role': 'build-only foreign binary seed',
                    'authority': 'rustc-1.99.0-src/src/stage0',
                    'authority_sha256': '759b73eca37a7b589b1ecc0fea77d94a1f8ca36cddb94f1401c72343e0dc1d4e',
                    'components': [{'url': 'https://static.rust-lang.org/dist/2026-08-20/rustc-1.98.0-x86_64-unknown-linux-gnu.tar.xz',
                                    'sha256': '0e37cb339f447fc44d6d781073bacacebfdc5612f2600e4c7e84c266f5f3aced'},
                                   {'url': 'https://static.rust-lang.org/dist/2026-08-20/rust-std-1.98.0-x86_64-unknown-linux-gnu.tar.xz',
                                    'sha256': 'f5022e6c95a5ad23cca2513dc8281200f585fa188de6370aa37b128a43f876a3'},
                                   {'url': 'https://static.rust-lang.org/dist/2026-08-20/cargo-1.98.0-x86_64-unknown-linux-gnu.tar.xz',
                                    'sha256': '2f512d170d3dd23e16ababcda32ee2e6d5172d861a7af1f504e0b1e270cafab9'}]},
 'source_dependencies': 'Vendored crates and LLVM from exact publisher source archive; Cargo '
                        'offline and locked-deps required.',
 'output_policy': 'Only x.py source-built stage2 installation; bootstrap directory is outside '
                  'DESTDIR.'}
