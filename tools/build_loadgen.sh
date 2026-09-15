#!/usr/bin/env bash
# Build the pinned loadgen with the reviewed local retry patch before any EC2 work.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_commit=801c3c369a0e8ff6f40a0af21aa5203f3689d65d
build_dir="${LOADGEN_BUILD_DIR:-$root/.loadgen-build}"
loadgen_goarch="${LOADGEN_GOARCH:-amd64}"
mkdir -p "$build_dir"
source_dir=$(mktemp -d "$build_dir/source.XXXXXX")
trap 'rm -rf "$source_dir"' EXIT
# Fetch the exact Git object; do not follow a moving branch or release tag.
git -C "$source_dir" init -q
git -C "$source_dir" fetch -q --depth 1 https://github.com/edgedelta/loadgen.git "$source_commit"
git -C "$source_dir" checkout -q --detach FETCH_HEAD
[[ $(git -C "$source_dir" rev-parse HEAD) == "$source_commit" ]]
git -C "$source_dir" apply "$root/patches/loadgen-retry.patch"
cp "$root"/loadgen_extensions/*.go "$source_dir/"
python3 - "$source_dir/main.go" <<'PYTHON'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
needle = 'config := parseFlags()'
assert s.count(needle) == 1
s = s.replace(needle, needle + '\n\tif *fixedRate != 0 { if err := runFixed(config); err != nil { log.Fatal(err) }; return }')
p.write_text(s)
PYTHON
if [[ "${1:-}" == "--test" ]]; then
  (cd "$source_dir" && go test -race ./... && go vet ./...)
fi
(cd "$source_dir" && CGO_ENABLED=0 GOOS=linux GOARCH="$loadgen_goarch" go build -trimpath -buildvcs=false -o "$build_dir/loadgen" .)
python3 - "$root" "$source_commit" "$build_dir" "$loadgen_goarch" <<'PY'
import hashlib, json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
metadata = {'version': '1.1.0+connection-retries.1+fixed-rate.1', 'source_commit': sys.argv[2],
            'build_script_sha256': sha(root / 'tools/build_loadgen.sh'),
            'patch_sha256': sha(root / 'patches/loadgen-retry.patch'),
            'extensions_sha256': {p.name: sha(p) for p in sorted((root / 'loadgen_extensions').glob('*.go'))},
            'fixed_payload_sha256': sha(root / 'payloads/fixed-nginx.ndjson'),
            'binary_sha256': sha(pathlib.Path(sys.argv[3]) / 'loadgen'),
            'goos': 'linux', 'goarch': sys.argv[4],
            'go_version': subprocess.check_output(['go', 'version'], text=True).strip(),
            'max_retries': 2, 'retry_ambiguous': True,
            'delivery_semantics': 'at-least-once; possible duplicates; failures may remain'}
(pathlib.Path(sys.argv[3]) / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
PY
