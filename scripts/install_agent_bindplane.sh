#!/usr/bin/env bash
set -euo pipefail

version=$(curl -fLsS --retry 3 https://api.github.com/repos/observIQ/bindplane-otel-collector/releases/latest | jq -er '.tag_name')
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
base="https://github.com/observIQ/bindplane-otel-collector/releases/download/$version"
package="observiq-otel-collector_${version}_linux_amd64.deb"
checksums="observiq-otel-collector-${version}-SHA256SUMS"
curl -fLsS --retry 3 -O "$base/$package"
curl -fLsS --retry 3 -O "$base/$checksums"
awk -v package="$package" '$2 == package || $2 == "*" package { print; found=1 } END { if (!found) exit 1 }' "$checksums" > bindplane.sha256
sha256sum --check bindplane.sha256
sudo dpkg -i "$package"
sudo systemctl stop observiq-otel-collector
rm "$package" "$checksums" bindplane.sha256
