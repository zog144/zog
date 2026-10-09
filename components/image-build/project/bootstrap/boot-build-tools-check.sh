set -eu
ninja --version
meson --version
work=$(mktemp -d /tmp/zog-boot-tools-XXXXXX)
trap 'rm -rf "$work"' EXIT
cd "$work"
cat > meson.build <<'MESON'
project('zog-boot-tool-check', 'c', version: '1.0')
program = executable('zog-probe', 'main.c', install: true)
test('boot-build-tools-c-execution', program)
MESON
cat > main.c <<'C'
#include <stdio.h>
int main(void) { puts("ZOG_BOOT_BUILD_TOOLS_C_PASS"); return 0; }
C
meson setup build --prefix=/usr --wrap-mode=nodownload
meson compile -C build -j 2
meson test -C build --print-errorlogs
DESTDIR="$work/install" meson install -C build --no-rebuild
"$work/install/usr/bin/zog-probe"
ninja -C build -n | grep 'no work to do'
printf '%s\n' ZOG_BOOT_BUILD_TOOLS_INSTALLED_PASS
