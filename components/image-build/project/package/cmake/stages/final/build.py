# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'cd upstream/cmake-4.4.4\n'
                './bootstrap --prefix=/usr --parallel=8 -- -DCMAKE_USE_OPENSSL=ON '
                '-DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'cd upstream/cmake-4.4.4\nmake -j8']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/cmake-4.4.4\n'
           'mkdir -p zog-check\n'
           "cat > zog-check/CMakeLists.txt <<'EOF'\n"
           'cmake_minimum_required(VERSION 3.20)\n'
           'project(zog_probe C CXX)\n'
           'enable_testing()\n'
           'add_executable(probe probe.cpp)\n'
           'add_test(NAME compiled-probe COMMAND probe)\n'
           'EOF\n'
           "printf 'int main() { return 0; }\\n' > zog-check/probe.cpp\n"
           './bin/cmake -S zog-check -B zog-check-build\n'
           './bin/cmake --build zog-check-build -j 2\n'
           '(cd zog-check-build && ../bin/ctest --output-on-failure)\n'
           './bin/cmake --version\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/cmake-4.4.4\nmake DESTDIR="$DESTDIR" install']],
 'environment': {}}
