set -eu
# Build-only fixture must not leak into the accepted runtime root.
test ! -e /usr/share/licenses/build-environment/COPYRIGHT
if test -f /etc/os-release; then
    ! grep -q "^BUILD_ID=systemd-261.2-test$" /etc/os-release
fi
for program in systemctl journalctl udevadm networkctl resolvectl timedatectl; do
    "$program" --version
 done
/usr/lib/systemd/systemd --version | grep '^systemd 261'
for program in systemd-journald systemd-udevd systemd-networkd systemd-resolved systemd-timesyncd; do
    test -x "/usr/lib/systemd/$program"
done
test -f /usr/share/zoneinfo/Europe/Berlin
test -f /usr/share/zoneinfo/UTC
pkg-config --exists libsystemd libudev
work=$(mktemp -d /tmp/zog-systemd-core-XXXXXX)
trap 'rm -rf "$work"' EXIT
cd "$work"
cat > interface.c <<'C'
#include <systemd/sd-id128.h>
#include <libudev.h>
#include <assert.h>
#include <string.h>
int main(void) {
    sd_id128_t id;
    char text[SD_ID128_STRING_MAX];
    const char *expected = "0123456789abcdef0123456789abcdef";
    assert(sd_id128_from_string(expected, &id) == 0);
    assert(strcmp(sd_id128_to_string(id, text), expected) == 0);
    struct udev *context = udev_new();
    assert(context);
    udev_unref(context);
    return 0;
}
C
gcc interface.c -o interface $(pkg-config --cflags --libs libsystemd libudev)
./interface
cat > fixture.service <<'UNIT'
[Unit]
Description=Zog offline unit verification
DefaultDependencies=no
[Service]
Type=oneshot
ExecStart=/usr/bin/true
UNIT
systemd-analyze verify --man=no "$work/fixture.service"
printf '%s\n' ZOG_SYSTEMD_CORE_INSTALLED_PASS
