#!/usr/bin/env bash

set -eo pipefail


sudo apt-get update -qq
sudo apt-get install -y -qq curl jq netcat-openbsd ca-certificates python3

# Built and uploaded by this benchmark from pinned source plus the retry patch.
sudo install -m 0755 /tmp/benchmark-loadgen /usr/local/bin/loadgen
rm /tmp/benchmark-loadgen

loadgen --help

# create benchmark scripts directory
mkdir -p ~/benchmark_scripts
