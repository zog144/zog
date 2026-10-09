# Data only; parsed with ast.literal_eval.
{'prepare': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              "python3 - <<'ZOG_VENDOR'\n"
              'import pathlib,hashlib,tomllib,json\n'
              'root=pathlib.Path.cwd()\n'
              "src=root/'upstream/cryptography-50.0.2'\n"
              "lock=(src/'Cargo.lock').read_bytes()\n"
              'assert '
              "hashlib.sha256(lock).hexdigest()=='98778208027ce05bfff0db88c290f28355eb20e685f0c728775359fb91a1a4c4'\n"
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
              'ZOG_VENDOR\n'
              'cd upstream/cryptography-50.0.2\n'
              "python3 - <<'ZOG_REQUIREMENTS'\n"
              'import importlib.metadata,pathlib,tomllib\n'
              'from packaging.requirements import Requirement\n'
              'for raw in '
              "tomllib.loads(pathlib.Path('pyproject.toml').read_text())['build-system']['requires']:\n"
              ' requirement=Requirement(raw)\n'
              ' if requirement.marker is None or requirement.marker.evaluate():\n'
              '  version=importlib.metadata.version(requirement.name)\n'
              '  assert version in requirement.specifier,(raw,version)\n'
              "  print('ZOG_BUILD_REQUIREMENT',requirement.name,version)\n"
              'ZOG_REQUIREMENTS\n']],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/cryptography-50.0.2\n'
            'maturin build --release --frozen --compatibility linux --skip-auditwheel '
            '--interpreter /usr/bin/python3 --out dist\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/cryptography-50.0.2\n'
           "python3 - <<'ZOG_WHEEL'\n"
           'import pathlib,zipfile,email,tempfile,sys\n'
           "wheels=list(pathlib.Path('dist').glob('*.whl'));assert len(wheels)==1\n"
           "with tempfile.TemporaryDirectory(prefix='zog-crypto-test-') as directory:\n"
           ' with zipfile.ZipFile(wheels[0]) as z:\n'
           '  assert z.testzip() is None\n'
           "  assert all(not n.startswith('/') and '..' not in pathlib.PurePosixPath(n).parts for "
           'n in z.namelist())\n'
           '  metadata=email.message_from_bytes(z.read(next(n for n in z.namelist() if '
           "n.endswith('.dist-info/METADATA'))))\n"
           "  assert metadata['Name']=='cryptography' and metadata['Version']=='50.0.2'\n"
           '  z.extractall(directory)\n'
           ' sys.path.insert(0,directory)\n'
           ' exec("import hashlib, pathlib, ssl, subprocess\\nimport cryptography\\nfrom '
           'cryptography.hazmat.bindings import _rust\\nfrom '
           'cryptography.hazmat.backends.openssl.backend import backend\\nfrom '
           'cryptography.hazmat.primitives.ciphers.aead import AESGCM\\nfrom '
           'cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\\nfrom '
           'cryptography.hazmat.primitives import serialization, hashes\\nfrom '
           'cryptography.exceptions import InvalidSignature, InvalidTag\\nassert '
           "cryptography.__version__ == '50.0.2'\\nassert backend.openssl_version_text() == "
           'ssl.OPENSSL_VERSION\\nlibrary = pathlib.Path(_rust.__file__)\\nassert '
           "library.is_file() and '.so' in library.name\\nneeded = "
           "subprocess.check_output(['readelf', '-d', str(library)], text=True)\\nassert "
           "'libcrypto.so.' in needed, needed\\nassert '.libs/' not in needed and 'RPATH' not in "
           "needed and 'RUNPATH' not in needed, needed\\nprint('ZOG_CRYPTOGRAPHY_NATIVE_OPENSSL', "
           'backend.openssl_version_text(), library)\\nh = hashes.Hash(hashes.SHA256()); '
           "h.update(b'abc')\\nassert h.finalize().hex() == hashlib.sha256(b'abc').hexdigest()\\n# "
           'NIST SP 800-38D AES-128-GCM zero-key/IV, one-block known-answer case.\\naead = '
           'AESGCM(bytes(16)); nonce = bytes(12)\\nexpected = '
           "bytes.fromhex('0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf')\\nassert "
           "aead.encrypt(nonce, bytes(16), b'') == expected\\nassert aead.decrypt(nonce, expected, "
           "b'') == bytes(16)\\ntry:\\n    aead.decrypt(nonce, "
           "expected[:-1]+bytes([expected[-1]^1]), b'')\\nexcept InvalidTag:\\n    "
           "pass\\nelse:\\n    raise AssertionError('altered GCM tag "
           "accepted')\\nprint('ZOG_CRYPTOGRAPHY_AESGCM_PASS')\\n# RFC 8032 section 7.1 test 1 "
           '(empty message).\\nseed = '
           "bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')\\nkey "
           '= Ed25519PrivateKey.from_private_bytes(seed)\\npublic = key.public_key()\\nassert '
           'public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex() '
           "== 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'\\nsignature = "
           "key.sign(b'')\\nexpected_signature = bytes.fromhex(\\n    "
           "'e5564300c360ac729086e2cc806e828a'\\n    '84877f1eb8e5d974d873e06522490155'\\n    "
           "'5fb8821590a33bacc61e39701cf9b46b'\\n    "
           "'d25bf5f0595bbe24655141438e7a100b'\\n)\\nassert len(expected_signature) == 64, "
           "'invalid RFC 8032 fixture length'\\nassert signature == expected_signature, 'RFC 8032 "
           "signature mismatch'\\npublic.verify(signature, b'')\\ntry:\\n    "
           "public.verify(signature, b'altered')\\nexcept InvalidSignature:\\n    "
           "pass\\nelse:\\n    raise AssertionError('altered signed message accepted')\\nencoded = "
           'key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, '
           'serialization.NoEncryption())\\nassert serialization.load_pem_private_key(encoded, '
           "None).sign(b'') == "
           'signature\\nprint(\'ZOG_CRYPTOGRAPHY_ED25519_PASS\')\\nprint(\'ZOG_CRYPTOGRAPHY_ACCEPTANCE_PASS\')\\n")\n'
           'ZOG_WHEEL\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/cryptography-50.0.2\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n']],
 'environment': {'CARGO_NET_OFFLINE': 'true',
                 'CARGO_BUILD_JOBS': '6',
                 'PIP_NO_INDEX': '1',
                 'PYTHONNOUSERSITE': '1',
                 'OPENSSL_DIR': '/usr',
                 'OPENSSL_NO_VENDOR': '1',
                 'OPENSSL_STATIC': '0',
                 'CRYPTOGRAPHY_BUILD_OPENSSL_NO_LEGACY': '1',
                 'PYO3_PYTHON': '/usr/bin/python3'}}
