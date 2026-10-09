# Data only; parsed with ast.literal_eval.
{'project': 'sqlite',
 'stage_id': 'final',
 'accepted_toolchain_requirements': ['gcc',
                                     'glibc',
                                     'make',
                                     'tcl',
                                     'readline',
                                     'ncurses',
                                     'zlib'],
 'toolchain_note': 'Build tools and preexisting libraries are supplied by the '
                   'bound accepted toolchain generation, not rebuilt as recipe '
                   'nodes. Tcl development files are checked in the configure '
                   'job and linked in an executable smoke test; missing files '
                   'fail before configure. Explicit --with-tcl prevents silent '
                   'Tcl disablement.',
 'required_toolchain_files': ['usr/bin/tclsh8.6',
                              'usr/lib/tclConfig.sh',
                              'usr/include/tcl.h',
                              'usr/lib/libtcl8.6.so']}
