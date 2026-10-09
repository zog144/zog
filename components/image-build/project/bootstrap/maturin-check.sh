set -eu
maturin --version
python3 -c 'import maturin; assert callable(maturin.build_wheel); print("ZOG_MATURIN_BACKEND_IMPORT")'
work=$(mktemp -d /tmp/zog-maturin-check.XXXXXX)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1])" "$work"' EXIT
cd "$work"
mkdir src
cat > Cargo.toml <<'TOML'
[package]
name = "zog-maturin-probe"
version = "0.1.0"
edition = "2024"
TOML
cat > pyproject.toml <<'TOML'
[build-system]
requires = ["maturin>=1.14.1,<2"]
build-backend = "maturin"
[project]
name = "zog-maturin-probe"
version = "0.1.0"
[tool.maturin]
bindings = "bin"
TOML
cat > src/main.rs <<'RUST'
fn main() { println!("ZOG_MATURIN_INSTALLED_PROBE_OK"); }
RUST
export CARGO_NET_OFFLINE=true MATURIN_NO_INSTALL_RUST=1 PIP_NO_INDEX=1
cargo generate-lockfile --offline
python3 - <<'PY'
import maturin,pathlib
pathlib.Path('wheels').mkdir()
print(maturin.build_wheel(str(pathlib.Path('wheels').resolve()), {'build-args':['--frozen','--compatibility','linux','--skip-auditwheel']}))
PY
python3 -m installer --destdir="$work/installed" wheels/*.whl
"$work/installed/usr/bin/zog-maturin-probe" | grep -Fx ZOG_MATURIN_INSTALLED_PROBE_OK
printf '%s\n' ZOG_MATURIN_INSTALLED_ACCEPTANCE_PASS
