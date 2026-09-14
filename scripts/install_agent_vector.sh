#!/usr/bin/env bash
set -euo pipefail
version=$(curl -fLsS --retry 3 'https://api.github.com/repos/vectordotdev/vector/releases?per_page=100' | jq -er '[.[] | select(.draft == false and .prerelease == false) | .tag_name | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+$")) | ltrimstr("v")] | sort_by(split(".") | map(tonumber)) | last // error("No stable Vector release found")' )
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fLsS --retry 3 "https://packages.timber.io/vector/$version/vector-$version-x86_64-unknown-linux-gnu.tar.gz" -o "$work/vector.tgz"
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
