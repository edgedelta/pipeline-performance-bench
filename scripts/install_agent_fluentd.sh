#!/usr/bin/env bash

set -euo pipefail

# Resolve the current package generation; install the latest stable Fluentd gem
# into its bundled Ruby so a package channel cannot hold the agent back.
version=$(curl -fLsS --retry 3 https://api.github.com/repos/fluent/fluent-package-builder/releases/latest | jq -er '.tag_name | ltrimstr("v")')
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
major=${version%%.*}
curl -fsSL --retry 3 "https://fluentd.cdn.cncf.io/sh/install-ubuntu-noble-fluent-package${major}-lts.sh" | sh

# fluentd >= 1.20 depends on a json gem newer than the one bundled with the
# package, and that gem ships a C extension, so the host needs a compiler.
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -qq build-essential
sudo /opt/fluent/bin/fluent-gem install fluentd --no-document

# S3 output plugin is not bundled with fluent-package; install it into the
# bundled Ruby. (record_transformer and grep filters are core.)
sudo /opt/fluent/bin/fluent-gem install fluent-plugin-s3

sudo systemctl stop fluentd || true
