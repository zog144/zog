"""Recorded accounts and source-built locale data for compiler test roots."""
from pathlib import Path
from .errors import ImageBuildError


def account_files(policy):
    uid, gid = policy.get('execution_user_id'), policy.get('execution_group_id')
    if any(type(value) is not int or value <= 0 or value >= 65534 for value in (uid, gid)):
        raise ImageBuildError('compiler tests require explicit unprivileged build identities')
    return {
        'etc/passwd': ('root:x:0:0:Root:/root:/bin/bash\n'
                       f'build-user:x:{uid}:{gid}:Build user:/tmp:/bin/bash\n'
                       'nobody:x:65534:65534:Nobody:/nonexistent:/bin/false\n'),
        'etc/group': f'root:x:0:\nbuild-user:x:{gid}:\nnogroup:x:65534:\n',
    }


def install_accounts(root, files):
    root = Path(root)
    for name, content in files.items():
        if name not in ('etc/passwd', 'etc/group'):
            raise ImageBuildError('unsupported compiler account file')
        path = root / name
        if path.is_symlink() or (root / 'etc').is_symlink():
            raise ImageBuildError('compiler account path traverses a symlink')
        if path.exists() and (not path.is_file() or path.read_text() != content):
            raise ImageBuildError('conflicting compiler accounts: ' + name)
    (root / 'etc').mkdir(exist_ok=True)
    for name, content in files.items():
        path = root / name
        if not path.exists():
            path.write_text(content)
            path.chmod(0o644)


GENERATE_LOCALE = r'''set -eu
test "$(id -un)" = build-user
test -f /usr/share/i18n/locales/C
test -f /usr/share/i18n/charmaps/UTF-8.gz
mkdir -p /image-build/output/usr/lib/locale
localedef --no-archive -i C -f UTF-8 /image-build/output/usr/lib/locale/C.utf8
LOCPATH=/image-build/output/usr/lib/locale python3 - <<'CHECK'
import locale
locale.setlocale(locale.LC_ALL, 'C.UTF-8')
assert locale.nl_langinfo(locale.CODESET) == 'UTF-8'
print('Source-built C.UTF-8 locale generated and verified')
CHECK
'''

ACCOUNT_PREFLIGHT = r'''
import pwd, grp, locale, subprocess
account = pwd.getpwuid(os.getuid())
assert account.pw_name == 'build-user' and account.pw_dir == os.environ['HOME']
assert grp.getgrgid(os.getgid()).gr_name == 'build-user'
assert pwd.getpwnam('root').pw_uid == 0
locale.setlocale(locale.LC_ALL, 'C.UTF-8')
assert locale.nl_langinfo(locale.CODESET) == 'UTF-8'
probe = subprocess.run(['/bin/bash', '-c', 'printf locale-ok'],
                       env=dict(os.environ, LC_ALL='C.UTF-8'), capture_output=True, check=True)
assert probe.stdout == b'locale-ok' and not probe.stderr
print('Build accounts, home directory and UTF-8 locale preflight passed')
'''
