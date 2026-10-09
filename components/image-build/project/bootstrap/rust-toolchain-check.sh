set -eu
cmake --version
ctest --version
pkg-config --modversion openssl libcurl
curl --version
mkdir -p /image-build/source/probe
cd /image-build/source/probe
cat > CMakeLists.txt <<'EOF'
cmake_minimum_required(VERSION 3.20)
project(zog_native C CXX)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
add_executable(probe probe.c)
target_link_libraries(probe PRIVATE CURL::libcurl OpenSSL::SSL)
enable_testing()
add_test(NAME probe COMMAND probe)
EOF
cat > probe.c <<'EOF'
#include <curl/curl.h>
#include <openssl/ssl.h>
int main(void) { const curl_version_info_data *v=curl_version_info(CURLVERSION_NOW); SSL_CTX *ctx=SSL_CTX_new(TLS_method()); if (!ctx || !v || !(v->features & CURL_VERSION_SSL)) return 1; SSL_CTX_free(ctx); return 0; }
EOF
cmake -S . -B build
cmake --build build -j2
ctest --test-dir build --output-on-failure
printf 'ZOG_NATIVE_PREREQUISITES_ACCEPTED\n'
rustc --version --verbose
cargo --version
mkdir -p /image-build/source/rust-check/src
cd /image-build/source/rust-check
cat > Cargo.toml <<'EOF'
[package]
name = "zog_rust_acceptance"
version = "0.1.0"
edition = "2024"
EOF
cat > src/main.rs <<'EOF'
fn main() { println!("ZOG_RUST_ACCEPTED"); }
#[test] fn arithmetic() { assert_eq!(2 + 2, 4); }
EOF
cargo generate-lockfile --offline
cargo build --frozen
cargo test --frozen
cargo run --frozen
