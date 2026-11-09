#!/usr/bin/env bash
set -euo pipefail
# GitHub incidents last minutes, not seconds: retry for about two minutes.
retry=(--retry 8 --retry-delay 15 --retry-connrefused)
# The runner resolves the version with authenticated gh (tools/agent_versions.py);
# only ask the unauthenticated API when nothing was passed.
version=${VECTOR_VERSION:-}
if [[ -z "$version" ]]; then
  version=$(curl -fLsS "${retry[@]}" 'https://api.github.com/repos/vectordotdev/vector/releases?per_page=100' | jq -er '[.[] | select(.draft == false and .prerelease == false) | .tag_name | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+$")) | ltrimstr("v")] | sort_by(split(".") | map(tonumber)) | last // error("No stable Vector release found")' )
fi
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fLsS "${retry[@]}" "https://github.com/vectordotdev/vector/releases/download/v$version/vector-$version-x86_64-unknown-linux-gnu.tar.gz" -o "$work/vector.tgz"
tar -xzf "$work/vector.tgz" -C "$work"
binary=$(find "$work" -type f -path '*/bin/vector' -print -quit)
[[ -n "$binary" ]]
sudo install -m 0755 "$binary" /usr/local/bin/vector
sudo mkdir -p /etc/vector /var/lib/vector
sudo tee /etc/systemd/system/vector.service >/dev/null <<'UNIT'
[Unit]
Description=Vector pipeline benchmark
After=network-online.target
[Service]
ExecStart=/usr/local/bin/vector --config /etc/vector/vector.yaml
Restart=no
LimitNOFILE=1048576
TimeoutStopSec=120
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl stop vector || true
/usr/local/bin/vector --version
