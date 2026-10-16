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
    id -u edgedelta >/dev/null 2>&1 || sudo useradd --system --user-group --home-dir /var/lib/edgedelta edgedelta
    curl -fLsS --retry 3 https://release.edgedelta.com/candidate/edgedelta-linux-amd64.sh -o /tmp/edgedelta-install.sh
    sudo env ED_API_KEY=benchmark-local ED_ENV_VARS=$'ED_SKIP_CONF_DOWNLOAD=1\nED_BACKEND_DISABLED=1\nED_DISABLE_CONF_RELOAD=1' bash /tmp/edgedelta-install.sh
    sudo systemctl stop edgedelta
    ;;
  cribl)
    curl -fLsS --retry 3 https://cdn.cribl.io/dl/4.20.2/cribl-4.20.2-7199aa90-linux-x64.tgz -o /tmp/cribl.tgz
    echo '629ef9d26d216a4f6f2b570bdc4d6eadf49ac03d98de84efd50e33768780d9f0  /tmp/cribl.tgz' | sha256sum --check
    sudo tar -xzf /tmp/cribl.tgz -C /opt
    ;;
  otelcol|bindplane|vector|fluentbit|fluentd)
    bash "scripts/install_agent_${vendor}.sh"
    if [[ "$vendor" == fluentd ]]; then sudo /opt/fluent/bin/fluent-gem install fluent-plugin-opentelemetry grpc --no-document; fi
    ;;
  *) echo "No installer for $vendor" >&2; exit 1 ;;
esac
