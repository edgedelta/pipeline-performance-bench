#!/usr/bin/env bash
set -euo pipefail
version=0.55.0
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
