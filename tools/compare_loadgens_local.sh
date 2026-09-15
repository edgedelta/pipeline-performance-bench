#!/usr/bin/env bash
# Native Linux Docker comparison; creates no cloud resources and publishes nothing.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
case $(docker info --format '{{.Architecture}}') in
  aarch64|arm64) loadgen_arch=arm64 ;;
  x86_64|amd64) loadgen_arch=amd64 ;;
  *) echo 'Unsupported Docker architecture' >&2; exit 1 ;;
esac
build="$root/.loadgen-build/comparison"
mkdir -p "$build"
LOADGEN_GOARCH="$loadgen_arch" LOADGEN_BUILD_DIR="$build/go" bash tools/build_loadgen.sh --test
CGO_ENABLED=0 GOOS=linux GOARCH="$loadgen_arch" go build -trimpath -o "$build/receiver" tools/loadgen_receiver/main.go
docker run --rm -v "$root:/src" -w /src -e CARGO_TARGET_DIR=/src/.loadgen-build/rust-linux rust:1.98.0-slim cargo build --locked --release --manifest-path loadgen-rust/Cargo.toml
docker run --rm --network none -v "$root:/src" -w /src python:3.12-slim python3 tests/loadgen_protocol.py .loadgen-build/comparison/go/loadgen .loadgen-build/rust-linux/release/pipeline-loadgen-rust
docker run --rm --network none -v "$root:/src" -w /src python:3.12-slim python3 tests/loadgen_protocol.py .loadgen-build/rust-linux/release/pipeline-loadgen-rust --task-mode
output="benchmark_results/loadgen-comparison-$(date -u +%Y%m%d-%H%M%S)"
docker run --rm --network none -v "$root:/src" -w /src python:3.12-slim python3 tools/compare_loadgens.py --go .loadgen-build/comparison/go/loadgen --rust .loadgen-build/rust-linux/release/pipeline-loadgen-rust --receiver .loadgen-build/comparison/receiver --out "$output" "$@"
cp "$build/go/provenance.json" "$output/go-provenance.json"
# Only allowlisted environment details, no host identifiers or Docker configuration.
{ go version; docker run --rm --network none rust:1.98.0-slim rustc --version; docker image inspect rust:1.98.0-slim python:3.12-slim --format '{{.Id}} {{.Os}}/{{.Architecture}}'; } > "$output/build-environment.txt"
python3 - "$output" <<'PYTHON'
import hashlib, json, pathlib, shutil, sys
out = pathlib.Path(sys.argv[1])
data = json.loads((out / 'data.json').read_text())
for name, expected in data['source_sha256'].items():
    source = pathlib.Path(name)
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Source changed during comparison: {name}')
    target = out / 'source' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
for name in ['tools/build_loadgen.sh', 'tools/compare_loadgens_local.sh', 'patches/loadgen-retry.patch', 'payloads/fixed-nginx.ndjson', *map(str, pathlib.Path('loadgen_extensions').glob('*.go'))]:
    target = out / 'source' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(name, target)
PYTHON
printf 'Comparison report: %s/%s/report.md\n' "$root" "$output"
