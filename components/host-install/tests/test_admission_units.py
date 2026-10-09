"""Check the boot transaction, not just syntax of isolated unit files."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd analyzer unavailable')
class AdmissionBootTests(unittest.TestCase):
    def test_boot_transaction_has_no_socket_bootstrap_cycle(self):
        source=Path(__file__).resolve().parents[1]/'examples/systemd'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);units=root/'etc/systemd/system';units.mkdir(parents=True)
            for name in ['host-install-admission.socket','host-install-admission@.service','host-install-prepare.service','host-install-identity.service']:
                shutil.copyfile(source/name,units/name)
            (units/'state.mount').write_text((source/'state.mount.in').read_text().replace('@STATE_PARTUUID@','11111111-1111-4111-8111-111111111111'))
            targets={
                'sysinit.target':'',
                'sockets.target':'Before=basic.target\n',
                'basic.target':'Requires=sysinit.target sockets.target\nAfter=sysinit.target sockets.target\n',
                'multi-user.target':'Requires=basic.target\nAfter=basic.target\nWants=host-install-admission.socket\n',
                'shutdown.target':'', 'local-fs.target':'', 'local-fs-pre.target':'',
            }
            for name,body in targets.items():(units/name).write_text('[Unit]\nDescription=Boot graph fixture\nDefaultDependencies=no\n'+body)
            exe=root/'usr/bin/host-install';exe.parent.mkdir(parents=True);exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o755)
            (root/'etc/passwd').write_text('root:x:0:0::/root:/bin/sh\nhost-discover:x:970:970::/state/host-discover:/usr/sbin/nologin\n')
            (root/'etc/group').write_text('root:x:0:\nhost-discover:x:970:\n')
            command=['systemd-analyze','verify','--generators=no','--man=no','--root='+temp,'multi-user.target']
            p=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertNotIn('ordering cycle',p.stderr.lower())
            # Negative control reproduces the shipped default-ordering bug.
            socket=units/'host-install-admission.socket';socket.write_text(socket.read_text().replace('DefaultDependencies=no\n',''))
            p=subprocess.run(command,capture_output=True,text=True)
            # systemd can return 0 after deleting jobs to break a cycle.
            self.assertIn('ordering cycle',p.stderr.lower())
