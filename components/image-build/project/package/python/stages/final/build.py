# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'for file in /usr/include/openssl/ssl.h /usr/include/sqlite3.h /usr/include/ffi.h '
                '/usr/include/expat.h /usr/include/gdbm.h /usr/include/bzlib.h /usr/include/lzma.h '
                '/usr/include/zstd.h /usr/include/mpdecimal.h /usr/include/uuid/uuid.h; do test -s '
                '"$file"; done; pkg-config --modversion openssl sqlite3 libffi expat libzstd; cd '
                'upstream/Python-3.15.0rc2; CFLAGS="-O2 -g -fstack-protector-strong '
                '-D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer" LDFLAGS="-Wl,-z,relro,-z,now" '
                'LIBFFI_LIBS="-lffi" LIBMPDEC_LIBS="-lmpdec" CURSES_LIBS="-lncursesw" '
                'PANEL_LIBS="-lpanelw -lncursesw" ./configure --prefix=/usr --libdir=/usr/lib '
                '--with-platlibdir=lib --enable-shared --without-static-libpython '
                '--without-ensurepip --with-openssl=/usr --with-openssl-rpath=no '
                '--with-ssl-default-suites=openssl --with-system-expat --with-system-libmpdec '
                '--enable-loadable-sqlite-extensions --with-dbmliborder=gdbm:ndbm --with-lto '
                '--enable-optimizations --enable-experimental-jit=no; grep -E '
                "'^MODULE__SSL_STATE=yes$' Makefile; grep -E '^MODULE__HASHLIB_STATE=yes$' "
                "Makefile; grep -E '^MODULE__SQLITE3_STATE=yes$' Makefile; grep -E "
                "'^MODULE__CTYPES_STATE=yes$' Makefile; grep -E '^MODULE_PYEXPAT_STATE=yes$' "
                "Makefile; grep -E '^MODULE__ELEMENTTREE_STATE=yes$' Makefile; grep -E "
                "'^MODULE__GDBM_STATE=yes$' Makefile; grep -E '^MODULE__DBM_STATE=yes$' Makefile; "
                "grep -E '^MODULE__BZ2_STATE=yes$' Makefile; grep -E '^MODULE__LZMA_STATE=yes$' "
                "Makefile; grep -E '^MODULE_ZLIB_STATE=yes$' Makefile; grep -E "
                "'^MODULE__ZSTD_STATE=yes$' Makefile; grep -E '^MODULE__DECIMAL_STATE=yes$' "
                "Makefile; grep -E '^MODULE_READLINE_STATE=yes$' Makefile; grep -E "
                "'^MODULE__CURSES_STATE=yes$' Makefile; grep -E '^MODULE__CURSES_PANEL_STATE=yes$' "
                "Makefile; grep -E '^MODULE__UUID_STATE=yes$' Makefile"]],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/Python-3.15.0rc2; make -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/Python-3.15.0rc2; printf "%s\\n" "TEST EXCEPTIONS: '
           'test.test_socket.RDSTest.testPeek, test.test_socket.RDSTest.testSelect, '
           'test.test_socket.RDSTest.testSendAndRecv, test.test_socket.RDSTest.testSendAndRecvMsg, '
           'test.test_socket.RDSTest.testSendAndRecvMulti"; LD_LIBRARY_PATH="$PWD" ./python - '
           "<<'ZOG_SOCKET_PROBE'\n"
           'import socket\n'
           "assert socket.getservbyname('domain', 'tcp') == 53\n"
           "assert socket.getservbyname('domain', 'udp') == 53\n"
           "assert socket.getservbyport(53, 'tcp') == 'domain'\n"
           "assert socket.getservbyport(53, 'udp') == 'domain'\n"
           'from test.test_socket import HAVE_SOCKET_RDS\n'
           'if HAVE_SOCKET_RDS:\n'
           '    with socket.socket(socket.AF_RDS, socket.SOCK_SEQPACKET) as receiver, '
           'socket.socket(socket.AF_RDS, socket.SOCK_SEQPACKET) as sender:\n'
           '        receiver.settimeout(5)\n'
           '        sender.settimeout(5)\n'
           "        receiver.bind(('127.0.0.1', 0))\n"
           "        sender.bind(('127.0.0.1', 0))\n"
           "        assert sender.sendto(b'zog-rds', receiver.getsockname()) == 7\n"
           "        assert receiver.recvfrom(32, socket.MSG_PEEK)[0] == b'zog-rds'\n"
           "        assert receiver.recvfrom(32)[0] == b'zog-rds'\n"
           'else:\n'
           "    print('RDS unavailable on this kernel; upstream RDS tests also report "
           "unsupported.', flush=True)\n"
           "print('Services fixture and bounded RDS probe passed; five RDS sender-close cases "
           "remain explicitly excepted.', flush=True)\n"
           'import faulthandler, unittest\n'
           'from test import test_socket as socket_tests\n'
           "expected = ['testPeek', 'testSelect', 'testSendAndRecv', 'testSendAndRecvMsg', "
           "'testSendAndRecvMulti']\n"
           'assert unittest.defaultTestLoader.getTestCaseNames(socket_tests.RDSTest) == expected, '
           "'RDS class changed; exception review required'\n"
           'if HAVE_SOCKET_RDS:\n'
           '    original_teardown = socket_tests.RDSTest.clientTearDown\n'
           '    originals = {name: getattr(socket_tests.RDSTest, name) for name in expected}\n'
           '    def synchronized_teardown(self):\n'
           '        try:\n'
           '            if not self.evt.wait(5):\n'
           "                raise TimeoutError('RDS receiver completion acknowledgement missing')\n"
           '        finally:\n'
           '            original_teardown(self)\n'
           '    def wrap_receiver(original):\n'
           '        def receive(self):\n'
           '            try:\n'
           '                return original(self)\n'
           '            finally:\n'
           '                self.evt.set()\n'
           '        return receive\n'
           '    socket_tests.RDSTest.clientTearDown = synchronized_teardown\n'
           '    for name, original in originals.items():\n'
           '        setattr(socket_tests.RDSTest, name, wrap_receiver(original))\n'
           '    faulthandler.dump_traceback_later(30, exit=True)\n'
           '    try:\n'
           '        result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(\n'
           '            socket_tests.RDSTest(name) for _ in range(100) for name in expected))\n'
           '        if not result.wasSuccessful() or result.testsRun != 500 or result.skipped:\n'
           "            raise RuntimeError('synchronized RDS class coverage failed or "
           "incomplete')\n"
           '    finally:\n'
           '        faulthandler.cancel_dump_traceback_later()\n'
           '        socket_tests.RDSTest.clientTearDown = original_teardown\n'
           '        for name, original in originals.items():\n'
           '            setattr(socket_tests.RDSTest, name, original)\n'
           "print('RDS supplemental checks complete; five original sender-close cases remain "
           "explicitly excepted.', flush=True)\n"
           'ZOG_SOCKET_PROBE\n'],
          ['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/Python-3.15.0rc2; LD_LIBRARY_PATH="$PWD" ./python -m test -j4 '
           '--timeout=900 --ignore test.test_socket.RDSTest.testPeek --ignore '
           'test.test_socket.RDSTest.testSelect --ignore test.test_socket.RDSTest.testSendAndRecv '
           '--ignore test.test_socket.RDSTest.testSendAndRecvMsg --ignore '
           'test.test_socket.RDSTest.testSendAndRecvMulti test_ssl test_hashlib test_sqlite3 '
           'test_ctypes test_socket test_select test_urllib test_urllib2 test_httpservers test_pwd '
           'test_grp test_fcntl test_os test_bz2 test_lzma test_zlib test_zstd test_decimal '
           'test_readline test_curses test_uuid test_pyexpat test_xml_etree test_dbm_gnu '
           'test_dbm_ndbm']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/Python-3.15.0rc2; make DESTDIR="$DESTDIR" install; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
