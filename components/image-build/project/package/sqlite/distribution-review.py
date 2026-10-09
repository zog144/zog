# Literal distribution evidence; not executable RPM input.
{'schema': 1,
 'specs': [{'url': 'https://src.fedoraproject.org/rpms/sqlite/raw/rawhide/f/sqlite.spec',
            'retrieved': '2026-10-03',
            'sha256': 'fa06d5e8fb4ffa941770260584f4ff508fed29cb8858b3e92e9b134fdb11c25c',
            'patch_inventory': ['Patch1: '
                                'sqlite-3.6.23-lemon-system-template.patch',
                                'Patch2: '
                                'sqlite-3.49.0-fix-lemon-missing-cflags.patch',
                                'Patch3: '
                                'sqlite-3.53.0-fix-testrunner-exiting-0.patch',
                                'Patch4: '
                                'sqlite-3.53.3-fix-fts3corrupt4-test.patch'],
            'build_requirements': ['BuildRequires: make',
                                   'BuildRequires: gcc gcc-c++',
                                   'BuildRequires: ncurses-devel '
                                   'readline-devel glibc-devel',
                                   'BuildRequires: /usr/bin/tclsh',
                                   'BuildRequires: zlib-ng-compat-devel',
                                   'BuildRequires: chrpath',
                                   'BuildRequires: libasan libubsan',
                                   'BuildRequires: tcl-devel']},
           {'url': 'https://api.opensuse.org/public/source/openSUSE:Factory/sqlite3/sqlite3.spec',
            'retrieved': '2026-10-03',
            'sha256': '2efa746bb797dc316c43471d8fbee371839e82d699c5ca32e34b311364ff56bf',
            'patch_inventory': ['Patch0:         '
                                'sqlite-3.6.23-lemon-system-template.patch',
                                'Patch1:         '
                                'sqlite-3.49.0-fix-lemon-missing-cflags.patch'],
            'build_requirements': ['BuildRequires:  automake',
                                   'BuildRequires:  libtool',
                                   'BuildRequires:  pkgconfig',
                                   'BuildRequires:  readline-devel',
                                   'BuildRequires:  tcl-devel',
                                   'BuildRequires:  unzip',
                                   'BuildRequires:  zlib-devel',
                                   'BuildRequires:  pkgconfig(zlib)',
                                   'BuildRequires:  libicu-devel']}],
 'patches_applied': [],
 'scope': 'Specs and selected policy/test patches reviewed; not a claim of '
          'exhaustive patch/security equivalence.',
 'decisions_document': 'docs/python-libraries.md',
 'dependency_dispositions': {'gcc gcc-c++ glibc-devel make': 'Required; bound '
                                                             'accepted '
                                                             'toolchain, '
                                                             'SQLite '
                                                             'compilation '
                                                             'already passed.',
                             'tcl-devel /usr/bin/tclsh': 'Required; bound '
                                                         'source-built Tcl '
                                                         '8.6.18 with '
                                                         'headers/library/config; '
                                                         'explicit configure '
                                                         'path and '
                                                         'compile/link/init '
                                                         'preflight.',
                             'readline-devel ncurses-devel': 'Readline '
                                                             'dependency node; '
                                                             'ncurses supplied '
                                                             'by accepted '
                                                             'toolchain.',
                             'zlib-devel zlib-ng-compat-devel pkgconfig(zlib)': 'zlib '
                                                                                'API '
                                                                                'supplied '
                                                                                'by '
                                                                                'accepted '
                                                                                'toolchain; '
                                                                                'no '
                                                                                'requirement '
                                                                                'for '
                                                                                'the '
                                                                                'distribution-specific '
                                                                                'zlib-ng '
                                                                                'implementation.',
                             'libasan libubsan': 'Present from accepted GCC; '
                                                 'Fedora sanitizer/debug '
                                                 'variants are not claimed by '
                                                 'our direct Tcl test target.',
                             'chrpath': 'Fedora install-time RPATH cleanup; no '
                                        'chrpath command in our recipe. '
                                        'Inspect target ELF RPATH separately '
                                        'before acceptance.',
                             'automake libtool pkgconfig unzip': 'openSUSE '
                                                                 'packaging/build '
                                                                 'tooling; '
                                                                 'pinned '
                                                                 'canonical '
                                                                 'tarball uses '
                                                                 'bundled '
                                                                 'autosetup '
                                                                 'and selected '
                                                                 'direct '
                                                                 'targets; not '
                                                                 'invoked by '
                                                                 'this Zog '
                                                                 'recipe.',
                             'libicu-devel': 'Conditional openSUSE feature, '
                                             'not selected in Zog; no ICU '
                                             'dependency for this build.'},
 'rechecked': '2026-10-03: both spec downloads matched recorded SHA256; '
              'reviewed full configure/build/check/install sections and pinned '
              'upstream Tcl detection.',
 'test_runner_review': 'Pinned upstream testrunner already returns failed-job '
                       'status and exits with it. Use isolated veryquick '
                       'runner; verify all jobs done, zero errors and affected '
                       'test file inclusion from its database. Fedora older '
                       'exit-status patch is not applicable; no patch or '
                       'waiver.'}
