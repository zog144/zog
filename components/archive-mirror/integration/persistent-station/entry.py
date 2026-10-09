"""Start station-access or its archive scheduler from the prepared environment."""
import os
import sys
python='/opt/station-python/bin/python'
if sys.argv[1]=='web':
    arguments=['-m','waitress','--listen=127.0.0.1:18080','--url-scheme=https','station_access_project.wsgi:application']
elif sys.argv[1]=='scheduler':
    arguments=['-m','zog.archive_mirror','scheduler']
else:
    raise SystemExit('Unknown program')
os.execv(python,[python,*arguments])
