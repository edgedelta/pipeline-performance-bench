#!/usr/bin/env bash
set -euo pipefail
version=5.1.2
sudo apt-get update -qq
sudo apt-get install -y ca-certificates curl gnupg
curl -fLsS --retry 3 https://packages.fluentbit.io/fluentbit.key | gpg --dearmor | sudo tee /usr/share/keyrings/fluentbit-keyring.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/fluentbit-keyring.gpg] https://packages.fluentbit.io/ubuntu/noble noble main' | sudo tee /etc/apt/sources.list.d/fluent-bit.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y "fluent-bit=$version*"
sudo systemctl stop fluent-bit
sudo mkdir -p /var/lib/fluent-bit/s3
/opt/fluent-bit/bin/fluent-bit --version
