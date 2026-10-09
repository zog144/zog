set -eu
rc=0
/usr/sbin/nologin -c 'exit 0' || rc=$?
test "$rc" -eq 1
/usr/bin/dbus-daemon --version
/usr/bin/dbus-run-session -- /bin/sh -eu -c 'dbus-send --session --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames'
test -f /usr/lib/systemd/system/dbus.service
/usr/sbin/ip -Version
/usr/sbin/ss -Version
/usr/sbin/tc -Version
pkg-config --exists libseccomp dbus-1
work=$(mktemp -d /tmp/zog-host-packages-XXXXXX)
trap 'rm -rf "$work"' EXIT
cd "$work"
cat > seccomp.c <<'C'
#include <seccomp.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <errno.h>
#include <assert.h>
int main(void) {
    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    assert(ctx);
    assert(seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(getppid), 0) == 0);
    assert(seccomp_load(ctx) == 0);
    errno = 0;
    assert(syscall(SYS_getppid) == -1 && errno == EPERM);
    seccomp_release(ctx);
    return 0;
}
C
gcc seccomp.c -o seccomp $(pkg-config --cflags --libs libseccomp)
./seccomp
truncate -s 32M ext4.img
/usr/sbin/mkfs.ext4 -F -q ext4.img
/usr/sbin/fsck.ext4 -f -n ext4.img
printf '%s\n' ZOG_HOST_BOOT_PACKAGES_INSTALLED_PASS
