#!/usr/bin/env bash

set -euo pipefail

# SSH can become available while first-boot package configuration is still running.
# A timeout/failure here stops provisioning; never delete package-manager locks.
echo "Waiting for cloud-init to finish (up to 10 minutes)..."
sudo timeout 600 cloud-init status --wait

# Applies to this bootstrap and later vendor installers on the same instance.
printf 'DPkg::Lock::Timeout "600";\nAcquire::Retries "3";\n' | sudo tee /etc/apt/apt.conf.d/99benchmark-lock-wait >/dev/null

# apt-get update's lists lock does not use DPkg::Lock::Timeout. Retry only lock
# contention, with a bounded budget; repository/configuration errors fail directly.
apt_update() {
  local attempt status output
  output=$(mktemp)
  for attempt in {1..12}; do
    if sudo env LC_ALL=C apt-get update -qq >"$output" 2>&1; then
      cat "$output"
      rm -f "$output"
      return 0
    else
      status=$?
    fi
    cat "$output" >&2
    if ! grep -Eq 'Could not get lock|Unable to acquire.*lock|Unable to lock directory' "$output" || [[ $attempt == 12 ]]; then
      rm -f "$output"
      return "$status"
    fi
    echo "Package list lock busy; retrying in 5 seconds ($attempt/12)..." >&2
    sleep 5
  done
}
apt_update
sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq curl jq netcat-openbsd ca-certificates python3

# Built and uploaded by this benchmark from pinned source plus the retry patch.
sudo install -m 0755 /tmp/benchmark-loadgen /usr/local/bin/loadgen
rm /tmp/benchmark-loadgen

sudo install -m 0755 /tmp/benchmark-loadgen-rust /usr/local/bin/loadgen-rust
rm /tmp/benchmark-loadgen-rust

loadgen --help
loadgen-rust --version

# create benchmark scripts directory
mkdir -p ~/benchmark_scripts
