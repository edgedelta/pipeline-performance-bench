#!/usr/bin/env bash
set -euo pipefail
vendor=$1
[[ "$vendor" =~ ^(red|edgedelta|bindplane|otelcol|vector|fluentbit|fluentd)$ ]]
terraform -chdir=otlpbench/infra init
terraform -chdir=otlpbench/infra apply -auto-approve
ip=$(terraform -chdir=otlpbench/infra output -raw ip)
key=otlpbench/infra/otlp-key.pem
# Terraform's local provider resolves filenames relative to its working directory.
opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=10 -i "$key")
for attempt in {1..30}; do
  if ssh "${opts[@]}" "ubuntu@$ip" true; then break; fi
  sleep 5
done
ssh "${opts[@]}" "ubuntu@$ip" 'mkdir -p bench'
tar --exclude=infra --exclude=__pycache__ -czf /tmp/otlp-bench-code.tgz otlpbench scripts
scp "${opts[@]}" /tmp/otlp-bench-code.tgz "ubuntu@$ip:/tmp/"
ssh "${opts[@]}" "ubuntu@$ip" 'cd bench && tar -xzf /tmp/otlp-bench-code.tgz'
if [[ "$vendor" == red ]]; then
  python3 tools/fetch_red.py /tmp/otlp-red-release
  scp "${opts[@]}" /tmp/otlp-red-release/red "ubuntu@$ip:/tmp/red"
fi
mkdir -p "otlp-results/$vendor"
collect() {
  scp "${opts[@]}" -r "ubuntu@$ip:bench/otlp-results/." "otlp-results/$vendor/" || true
}
trap collect EXIT
ssh "${opts[@]}" "ubuntu@$ip" "cd bench && bash otlpbench/install.sh '$vendor'"
ssh "${opts[@]}" "ubuntu@$ip" "cd bench && sudo env BENCHMARK_SHA='$GITHUB_SHA' .otlp-venv/bin/python -m otlpbench.runner --vendor '$vendor' --seconds 30 --rates 1000,10000"
