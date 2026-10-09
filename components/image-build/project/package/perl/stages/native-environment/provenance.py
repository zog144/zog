# Data only; parsed with ast.literal_eval.
{'lfs_edition': '13.1-systemd',
 'recipe_reference': 'https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter07/perl.html',
 'source_verification': {'url': 'https://www.cpan.org/src/5.0/perl-5.44.0.tar.xz',
                         'sha256': '505cf43912e9480495c344c70260452e32aa2a73c546a026b3f100053b23ce91',
                         'lfs_md5': '55761cf1543af326492fd194647796d1',
                         'bytes': 14919940,
                         'filename': 'perl-5.44.0.tar.xz',
                         'version': '5.44.0',
                         'reference': 'https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter03/packages.html'},
 'adaptations': ['Unprivileged box-control job; staged DESTDIR output.',
                 'Shared Info index excluded from package output.',
                 'Explicit man1/man3 directories and extensions; minimal root '
                 'has no system man defaults. Revision 2 corrects rejected '
                 'root-level .0 manual pages.'],
 'verification_scope': 'Combined environment functional probe; full upstream '
                       'test suites deferred.'}
