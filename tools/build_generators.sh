#!/usr/bin/env bash
# Build once on Ubuntu 24.04 x86_64, before provisioning any benchmark instances.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]] || ! grep -q '^VERSION_ID="24.04"' /etc/os-release; then
  echo 'Build on Ubuntu 24.04 x86_64 (matching the EC2 image), or supply a verified CI bundle via BENCHMARK_PREBUILT_LOADGEN=1.' >&2
  exit 1
fi
LOADGEN_BUILD_DIR="$root/.loadgen-build" LOADGEN_GOARCH=amd64 ./tools/build_loadgen.sh
cargo +1.98.0 build --locked --release --manifest-path loadgen-rust/Cargo.toml --target x86_64-unknown-linux-gnu --target-dir "$root/.loadgen-build/rust-target"
install -m 0755 .loadgen-build/rust-target/x86_64-unknown-linux-gnu/release/pipeline-loadgen-rust .loadgen-build/loadgen-rust
python3 tools/generator_bundle.py create .loadgen-build
