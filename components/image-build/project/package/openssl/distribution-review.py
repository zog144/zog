# Literal distribution evidence; not executable RPM input.
{'schema': 1,
 'specs': [{'url': 'https://src.fedoraproject.org/rpms/openssl/raw/rawhide/f/openssl.spec',
            'retrieved': '2026-10-03',
            'sha256': '60df60259b008ce9c0b1e8e60d2250ea1ce0de80776fdbf9c7f2e58181824a87',
            'patch_inventory': ['Patch0001: '
                                '0001-RH-Aarch64-and-ppc64le-use-lib64.patch',
                                'Patch0002: '
                                '0002-Add-a-separate-config-file-to-use-for-rpm-installs.patch',
                                'Patch0003: '
                                '0003-RH-Do-not-install-html-docs.patch',
                                'Patch0004: '
                                '0004-RH-Disable-signature-verification-with-bad-digests-R.patch',
                                'Patch0005: '
                                '0005-RH-Add-support-for-PROFILE-SYSTEM-system-default-cip.patch',
                                'Patch0006: '
                                '0006-RH-Add-FIPS_mode-compatibility-macro.patch',
                                'Patch0007: '
                                '0007-RH-Add-Kernel-FIPS-mode-flag-support-FIXSTYLE.patch',
                                'Patch0008: '
                                '0008-RH-Allow-disabling-of-SHA1-signatures.patch',
                                'Patch0009: '
                                '0009-FIPS-Force-fips-provider-on.patch',
                                'Patch0010: '
                                '0010-FIPS-RAND-FIPS-140-3-DRBG-NEEDS-REVIEW.patch',
                                'Patch0011: '
                                '0011-FIPS-TLS-Enforce-EMS-in-TLS-1.2-NOTE.patch',
                                'Patch0012: '
                                '0012-FIPS-CMS-Set-default-padding-to-OAEP.patch',
                                'Patch0013: '
                                '0013-FIPS-PKCS12-PBMAC1-defaults.patch',
                                'Patch0014: '
                                '0014-FIPS-EC-disable-weak-curves.patch',
                                'Patch0015: '
                                '0015-Make-openssl-speed-run-in-FIPS-mode.patch',
                                'Patch0016: '
                                '0016-Allow-hybrid-MLKEM-in-FIPS-mode.patch'],
            'build_requirements': ['BuildRequires: gcc g++',
                                   'BuildRequires: coreutils, '
                                   'perl-interpreter, sed, zlib-devel, '
                                   '/usr/bin/cmp',
                                   'BuildRequires: lksctp-tools-devel',
                                   'BuildRequires: /usr/bin/rename',
                                   'BuildRequires: /usr/bin/pod2man',
                                   'BuildRequires: /usr/sbin/sysctl',
                                   'BuildRequires: perl(Test::Harness), '
                                   'perl(Test::More), perl(Math::BigInt)',
                                   'BuildRequires: '
                                   'perl(Module::Load::Conditional), '
                                   'perl(File::Temp)',
                                   'BuildRequires: perl(Time::HiRes), '
                                   'perl(Time::Piece), perl(IPC::Cmd), '
                                   'perl(Pod::Html), perl(Digest::SHA)',
                                   'BuildRequires: perl(FindBin), perl(lib), '
                                   'perl(File::Compare), perl(File::Copy), '
                                   'perl(bigint)',
                                   'BuildRequires: git-core',
                                   'BuildRequires: systemtap-sdt-devel']},
           {'url': 'https://api.opensuse.org/public/source/openSUSE:Factory/openssl-3/openssl-3.spec',
            'retrieved': '2026-10-03',
            'sha256': '655b7f750c4d466af3aa7edc2045497e04b7974858c709128b261f21c020a09d',
            'patch_inventory': ['Patch1:         openssl-no-html-docs.patch',
                                'Patch2:         openssl-truststore.patch',
                                'Patch3:         openssl-pkgconfig.patch',
                                'Patch4:         openssl-ppc64-config.patch',
                                'Patch5:         openssl-no-date.patch',
                                'Patch6:         '
                                'openssl-Add-support-for-PROFILE-SYSTEM-system-default-cipher.patch',
                                'Patch7:         '
                                'openssl-Add-FIPS_mode-compatibility-macro.patch',
                                'Patch8:         '
                                'openssl-Add-Kernel-FIPS-mode-flag-support.patch',
                                'Patch9:         openssl-Force-FIPS.patch',
                                'Patch10:        '
                                'openssl-disable-fipsinstall.patch',
                                'Patch11:        '
                                'openssl-load-legacy-provider.patch',
                                'Patch12:        openssl-FIPS-embed-hmac.patch',
                                'Patch13:        '
                                'openssl-Add-changes-to-ectest-and-eccurve.patch',
                                'Patch14:        '
                                'openssl-Disable-explicit-ec.patch',
                                'Patch15:        '
                                'openssl-skipped-tests-EC-curves.patch',
                                'Patch16:        '
                                'openssl-FIPS-140-3-keychecks.patch',
                                'Patch17:        openssl-FIPS-early-KATS.patch',
                                'Patch19:        '
                                'openssl-FIPS-limit-rsa-encrypt.patch',
                                'Patch20:        '
                                'openssl-FIPS-Expose-a-FIPS-indicator.patch',
                                'Patch21:        '
                                'openssl-FIPS-Use-OAEP-in-KATs-support-fixed-OAEP-seed.patch',
                                'Patch22:        '
                                'openssl-rand-Forbid-truncated-hashes-SHA-3-in-FIPS-prov.patch',
                                'Patch23:        '
                                'openssl-FIPS-Remove-X9.31-padding-from-FIPS-prov.patch',
                                'Patch24:        '
                                'openssl-pbkdf2-Set-minimum-password-length-of-8-bytes.patch',
                                'Patch25:        '
                                'openssl-FIPS-RSA-disable-shake.patch',
                                'Patch26:        '
                                'openssl-FIPS-RSA-encapsulate.patch',
                                'Patch27:        '
                                'openssl-DH-Disable-FIPS-186-4-type-parameters-in-FIPS-mode.patch',
                                'Patch28:        '
                                'openssl-FIPS-Add-SP800-56Br2-6.4.1.2.1-3.c-check.patch',
                                'Patch29:        '
                                'openssl-FIPS-Enforce-error-state.patch',
                                'Patch30:        '
                                'openssl-skip-quic-pairwise.patch',
                                'Patch31:        '
                                'openssl-FIPS-Fix-encoder-decoder-negative-test.patch',
                                'Patch32:        '
                                'openssl-FIPS-SUSE-FIPS-module-version.patch',
                                'Patch33:        '
                                'openssl-FIPS-EC-disable-weak-curves.patch',
                                'Patch34:        '
                                'openssl-FIPS-NO-DSA-Support.patch',
                                'Patch35:        '
                                'openssl-FIPS-NO-DES-support.patch',
                                'Patch36:        openssl-FIPS-NO-Kmac.patch',
                                'Patch37:        '
                                'openssl-FIPS-NO-PQ-ML-SLH-DSA.patch',
                                'Patch38:        '
                                'openssl-shared-jitterentropy.patch',
                                'Patch39:        '
                                'openssl-disable-75-test_quicapi-test.patch',
                                'Patch40:        '
                                'openssl-FIPS-enforce-EMS-support.patch',
                                'Patch41:        '
                                'openssl-Allow-disabling-of-SHA1-signatures.patch',
                                'Patch42:        '
                                'openssl-FIPS-Deny-SHA-1-sigver-in-FIPS-provider.patch',
                                'Patch43:        '
                                'openssl-FIPS-Allow-SHA1-in-seclevel-2-if-rh-allow-sha1-signatures.patch',
                                'Patch44:        '
                                'openssl-FIPS-Fix-openssl-speed-KMAC.patch',
                                'Patch45:        '
                                'openssl-Fix-Wfree-nonheap-object-warning.patch',
                                'Patch46:        openssl-CVE-2025-9230.patch',
                                'Patch47:        openssl-CVE-2025-9231.patch',
                                'Patch48:        openssl-CVE-2025-9232.patch',
                                'Patch50:        openssl-CVE-2026-22795.patch',
                                'Patch51:        openssl-CVE-2025-69420.patch',
                                'Patch52:        openssl-CVE-2025-69421.patch',
                                'Patch53:        openssl-CVE-2025-69419.patch',
                                'Patch54:        openssl-CVE-2025-66199.patch',
                                'Patch55:        openssl-CVE-2025-68160.patch',
                                'Patch56:        openssl-CVE-2025-69418.patch',
                                'Patch57:        openssl-CVE-2025-15469.patch',
                                'Patch58:        openssl-CVE-2025-15467.patch',
                                'Patch59:        '
                                'openssl-CVE-2025-15467-comments.patch',
                                'Patch60:        '
                                'openssl-CVE-2025-15467-test.patch',
                                'Patch61:        openssl-CVE-2025-11187.patch',
                                'Patch62:        openssl-CVE-2025-15468.patch',
                                'Patch63:        '
                                'openssl-crypto-mem.c-factor-out-memory-allocation-failure-reporting.patch',
                                'Patch64:        '
                                'openssl-Add-array-memory-allocation-routines.patch',
                                'Patch65:        openssl-CVE-2026-2673.patch',
                                'Patch66:        openssl-CVE-2026-28387.patch',
                                'Patch67:        openssl-CVE-2026-28388.patch',
                                'Patch68:        '
                                'openssl-CVE-2026-28388-tests.patch',
                                'Patch69:        openssl-CVE-2026-28389.patch',
                                'Patch70:        openssl-CVE-2026-31789.patch',
                                'Patch71:        openssl-CVE-2026-31790.patch',
                                'Patch72:        '
                                'openssl-CVE-2026-31790-tests.patch',
                                'Patch73:        '
                                'openssl-NULL-pointer-dereference-in-ocsp_find_signer_sk.patch',
                                'Patch74:        openssl-CVE-2026-28390.patch',
                                'Patch75:        '
                                'openssl-ppc64le-Optimized-MLKEM-NTT-supports-p8-ISA-2.07-and-above-architectures.patch',
                                'Patch76:        openssl-CVE-2026-45447.patch',
                                'Patch77:        openssl-CVE-2026-45446.patch',
                                'Patch78:        openssl-CVE-2026-42770.patch',
                                'Patch79:        openssl-CVE-2026-45445.patch',
                                'Patch80:        openssl-CVE-2026-42767.patch',
                                'Patch81:        openssl-CVE-2026-42768.patch',
                                'Patch82:        openssl-CVE-2026-42769.patch',
                                'Patch83:        openssl-CVE-2026-42766.patch',
                                'Patch84:        openssl-CVE-2026-34183.patch',
                                'Patch85:        openssl-CVE-2026-42764.patch',
                                'Patch86:        openssl-CVE-2026-34182.patch',
                                'Patch88:        openssl-CVE-2026-9076.patch',
                                'Patch89:        openssl-CVE-2026-7383.patch',
                                'Patch90:        openssl-CVE-2026-34180.patch',
                                'Patch91:        openssl-HollowByte.patch',
                                'Patch92:        openssl-CVE-2026-14456.patch',
                                'Patch93:        openssl-CVE-2026-14457.patch',
                                'Patch94:        openssl-CVE-2026-18798.patch',
                                'Patch95:        openssl-CVE-2026-34181.patch',
                                'Patch96:        openssl-CVE-2026-54874.patch',
                                'Patch97:        openssl-CVE-2026-63072.patch',
                                'Patch98:        openssl-CVE-2026-63073.patch',
                                'Patch99:        openssl-CVE-2026-63074.patch',
                                'Patch100:       openssl-CVE-2026-63075.patch',
                                'Patch101:       openssl-CVE-2026-63076.patch',
                                'Patch102:       openssl-CVE-2026-75803.patch'],
            'build_requirements': ['BuildRequires:  ulp-macros',
                                   'BuildRequires:  pkgconfig',
                                   'BuildRequires:  pkgconfig(zlib)',
                                   'BuildRequires:  jitterentropy-devel >= '
                                   '3.4.0',
                                   'BuildRequires:  fipscheck',
                                   'BuildRequires:  jitterentropy-devel >= '
                                   '3.4.0']}],
 'patches_applied': [],
 'scope': 'Specs and selected policy/test patches reviewed; not a claim of '
          'exhaustive patch/security equivalence.',
 'decisions_document': 'docs/python-libraries.md'}
