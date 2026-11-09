#!/usr/bin/env bash

set -euo pipefail

# GitHub incidents last minutes, not seconds: retry for about two minutes.
retry=(--retry 8 --retry-delay 15 --retry-connrefused)
# The runner resolves the version with authenticated gh (tools/agent_versions.py);
# only ask the unauthenticated API when nothing was passed.
otelcol_version=${OTELCOL_VERSION:-}
if [[ -z "$otelcol_version" ]]; then
  otelcol_version=$(curl -fLsS "${retry[@]}" "https://api.github.com/repos/open-telemetry/opentelemetry-collector-releases/releases/latest" \
    | jq -er '.tag_name | ltrimstr("v")')
fi

[[ "$otelcol_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]

curl -fLsS "${retry[@]}" -o otelcol-contrib.deb \
  "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${otelcol_version}/otelcol-contrib_${otelcol_version}_linux_amd64.deb"
sudo dpkg -i otelcol-contrib.deb
rm otelcol-contrib.deb

sudo systemctl stop otelcol-contrib || true
