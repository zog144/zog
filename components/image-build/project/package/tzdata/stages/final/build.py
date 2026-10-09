# Data only; parsed with ast.literal_eval.
{'configure': [],
 'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/tzdata-2026d\n'
            'mkdir -p build/zoneinfo\n'
            '/usr/sbin/zic -b fat -d build/zoneinfo africa antarctica asia australasia europe '
            'northamerica southamerica etcetera backward']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/tzdata-2026d\n'
           "python3 - <<'CHECK'\n"
           'from pathlib import Path\n'
           'from zoneinfo import ZoneInfo\n'
           'from datetime import datetime, timedelta\n'
           "root=Path('build/zoneinfo')\n"
           'def zone(name):\n'
           "    with (root/name).open('rb') as f:return ZoneInfo.from_file(f,key=name)\n"
           "b=zone('Europe/Berlin')\n"
           'assert datetime(2016,1,1,tzinfo=b).utcoffset()==timedelta(hours=1)\n'
           'assert datetime(2016,7,1,tzinfo=b).utcoffset()==timedelta(hours=2)\n'
           'assert datetime(2016,3,27,1,59,tzinfo=b).utcoffset()==timedelta(hours=1)\n'
           'assert datetime(2016,3,27,3,0,tzinfo=b).utcoffset()==timedelta(hours=2)\n'
           "assert datetime(2026,1,1,tzinfo=zone('UTC')).utcoffset()==timedelta(0)\n"
           "files=[f for f in root.rglob('*') if f.is_file()]\n"
           'assert len(files)>500\n'
           'for f in files:\n'
           "    with f.open('rb') as stream:ZoneInfo.from_file(stream)\n"
           "print('TZDATA_ZONEINFO_PASS',len(files))\n"
           'CHECK']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/tzdata-2026d\n'
              'install -d "$DESTDIR/usr/share/zoneinfo" "$DESTDIR/usr/share/licenses/tzdata"\n'
              'cp -a build/zoneinfo/. "$DESTDIR/usr/share/zoneinfo/"\n'
              'cp iso3166.tab zone.tab zone1970.tab zonenow.tab leap-seconds.list '
              '"$DESTDIR/usr/share/zoneinfo/"\n'
              'cp LICENSE "$DESTDIR/usr/share/licenses/tzdata/LICENSE"']]}
