#!/usr/bin/env bash
set -euo pipefail
vendor=$1
GITHUB_SHA=${GITHUB_SHA:-$(git rev-parse HEAD)}
scenarios=${OTLP_SCENARIOS:-}
signals=${OTLP_SIGNALS:-metrics,traces}
[[ "$signals" =~ ^(metrics|traces|metrics,traces)$ ]]
[[ "$scenarios" =~ ^[a-z,-]*$ ]]
[[ "$vendor" =~ ^(red|edgedelta|bindplane|otelcol|vector|fluentbit|fluentd|cribl)$ ]]
collect_and_cleanup() {
  local status=$?
  if [[ -n "${ip:-}" && -d "otlp-results/$vendor" ]]; then
    scp "${opts[@]}" -r "ubuntu@$ip:bench/otlp-results/." "otlp-results/$vendor/" || true
  fi
  if [[ "${OTLP_EXTERNAL_CLEANUP:-0}" != 1 && -f otlpbench/infra/terraform.tfstate ]]; then
    terraform -chdir=otlpbench/infra destroy -auto-approve || status=1
  fi
  if [[ -n "${archive:-}" ]]; then rm -f "$archive"; fi
  exit "$status"
}
trap collect_and_cleanup EXIT
terraform -chdir=otlpbench/infra init
terraform -chdir=otlpbench/infra apply -auto-approve
ip=$(terraform -chdir=otlpbench/infra output -raw ip)
key=otlpbench/infra/otlp-key.pem
# Terraform's local provider resolves filenames relative to its working directory.
opts=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=10 -i "$key")
for attempt in {1..30}; do
  if ssh "${opts[@]}" "ubuntu@$ip" true; then break; fi
  sleep 5
done
ssh "${opts[@]}" "ubuntu@$ip" 'sudo cloud-init status --wait; mkdir -p bench'
archive=$(mktemp /tmp/otlp-bench-code.XXXXXX)
tar --exclude=infra --exclude=__pycache__ -czf "$archive" otlpbench scripts
scp "${opts[@]}" "$archive" "ubuntu@$ip:/tmp/otlp-bench-code.tgz"
ssh "${opts[@]}" "ubuntu@$ip" 'cd bench && tar -xzf /tmp/otlp-bench-code.tgz'
if [[ "$vendor" == red ]]; then
  python3 tools/fetch_red.py /tmp/otlp-red-release
  scp "${opts[@]}" /tmp/otlp-red-release/red "ubuntu@$ip:/tmp/red"
fi
mkdir -p "otlp-results/$vendor"
ssh "${opts[@]}" "ubuntu@$ip" "cd bench && bash otlpbench/install.sh '$vendor'"
ssh "${opts[@]}" "ubuntu@$ip" "cd bench && sudo env BENCHMARK_SHA='$GITHUB_SHA' .otlp-venv/bin/python -m otlpbench.runner --vendor '$vendor' --seconds 30 --rates 1000,10000,25000,50000,125000 --scenarios '$scenarios' --signals '$signals'"
