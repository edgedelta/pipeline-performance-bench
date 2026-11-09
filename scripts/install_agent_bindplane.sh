#!/usr/bin/env bash
set -euo pipefail

# GitHub incidents last minutes, not seconds: retry for about two minutes.
retry=(--retry 8 --retry-delay 15 --retry-connrefused)
# The runner resolves the version with authenticated gh (tools/agent_versions.py),
# or the OTLP harness pins it; only ask the unauthenticated API when nothing was passed.
version=${BINDPLANE_VERSION:-}
if [[ -z "$version" ]]; then
  version=$(curl -fLsS "${retry[@]}" https://api.github.com/repos/observIQ/bindplane-otel-collector/releases/latest | jq -er '.tag_name')
fi
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
base="https://github.com/observIQ/bindplane-otel-collector/releases/download/$version"
package="observiq-otel-collector_${version}_linux_amd64.deb"
checksums="observiq-otel-collector-${version}-SHA256SUMS"
curl -fLsS "${retry[@]}" -O "$base/$package"
curl -fLsS "${retry[@]}" -O "$base/$checksums"
awk -v package="$package" '$2 == package || $2 == "*" package { print; found=1 } END { if (!found) exit 1 }' "$checksums" > bindplane.sha256
sha256sum --check bindplane.sha256
sudo dpkg -i "$package"
sudo systemctl stop observiq-otel-collector
rm "$package" "$checksums" bindplane.sha256
