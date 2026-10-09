# Data only; parsed with ast.literal_eval.
{'lfs_edition': '13.1-systemd',
 'recipe_reference': 'https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter07/util-linux.html',
 'source_verification': {'url': 'https://www.kernel.org/pub/linux/utils/util-linux/v2.42/util-linux-2.42.2.tar.xz',
                         'sha256': '03a05d3adf9602ef128f2da05b84b3205ce60c351e5737c0370f74000679ce8a',
                         'lfs_md5': '1d70131b70abda3dec3b37e282a20c96',
                         'bytes': 10658220,
                         'filename': 'util-linux-2.42.2.tar.xz',
                         'version': '2.42.2',
                         'reference': 'https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter03/packages.html'},
 'adaptations': ['Unprivileged box-control job; staged DESTDIR output.',
                 'Shared Info index excluded from package output.',
                 'Install ownership/setuid changes disabled for unprivileged staging.',
                 'Explicit bindir=/usr/bin and sbindir=/usr/sbin for isolated merged-/usr staging; /bin '
                 'symlinks from the base are absent in empty DESTDIR.'],
 'verification_scope': 'Combined environment functional probe; full upstream test suites deferred.'}
