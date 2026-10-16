#!/usr/bin/env bash
set -euo pipefail
vendor=$1
sudo apt-get update -qq
sudo apt-get -o DPkg::Lock::Timeout=180 install -y -qq python3-venv jq curl
python3 -m venv .otlp-venv
.otlp-venv/bin/pip install -r otlpbench/requirements.txt
case "$vendor" in
  red) bash scripts/install_agent_red.sh ;;
  edgedelta)
    curl -fLsS --retry 3 https://release.edgedelta.com/candidate/edgedelta-linux-amd64.sh -o /tmp/edgedelta-install.sh
    sudo env ED_API_KEY=benchmark-local ED_ENV_VARS='ED_SKIP_CONF_DOWNLOAD=1 ED_BACKEND_DISABLED=1 ED_DISABLE_CONF_RELOAD=1' bash /tmp/edgedelta-install.sh
    sudo systemctl stop edgedelta
    ;;
  otelcol|bindplane|vector|fluentbit|fluentd)
    bash "scripts/install_agent_${vendor}.sh"
    if [[ "$vendor" == fluentd ]]; then sudo /opt/fluent/bin/fluent-gem install fluent-plugin-opentelemetry grpc --no-document; fi
    ;;
  *) echo "No installer for $vendor" >&2; exit 1 ;;
esac
