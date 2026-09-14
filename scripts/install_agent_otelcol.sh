#!/usr/bin/env bash

set -euo pipefail

otelcol_version=$(curl -fLsS --retry 3 "https://api.github.com/repos/open-telemetry/opentelemetry-collector-releases/releases/latest" \
  | jq -er '.tag_name | ltrimstr("v")')

[[ "$otelcol_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]

curl -fLsS --retry 3 -o otelcol-contrib.deb \
  "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${otelcol_version}/otelcol-contrib_${otelcol_version}_linux_amd64.deb"
sudo dpkg -i otelcol-contrib.deb
rm otelcol-contrib.deb

sudo systemctl stop otelcol-contrib || true
