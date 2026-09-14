#!/usr/bin/env bash

set -eo pipefail


sudo apt-get update -qq
sudo apt-get install -y -qq curl jq netcat-openbsd ca-certificates python3

loadgen_version="1.1.0"
# Install Go
curl -fLsS --retry 3 https://github.com/edgedelta/loadgen/releases/download/v${loadgen_version}/loadgen_${loadgen_version}_Linux_x86_64.tar.gz --output loadgen.tar.gz
sudo tar -xf loadgen.tar.gz -C /usr/local/bin/
rm loadgen.tar.gz

loadgen --help

# create benchmark scripts directory
mkdir -p ~/benchmark_scripts
