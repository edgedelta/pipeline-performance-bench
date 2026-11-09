#!/usr/bin/env bash

set -e

git_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$git_root"
# shellcheck source=./functions.sh
source "functions.sh" || exit 1

ed_benchmark=0
cribl_benchmark=0

# All pipeline cases and vendors the suite knows about, in canonical run order.
ALL_CASES=("pass-through" "filter" "mask" "lookup")
ALL_VENDORS=("edgedelta" "red" "cribl" "otelcol" "fluentd" "vector" "fluentbit" "bindplane")

# Selections default to everything (preserves the previous "run all" behaviour).
SELECTED_CASES=("${ALL_CASES[@]}")
SELECTED_VENDORS=("${ALL_VENDORS[@]}")

usage() {
  cat <<EOF
Usage: ./run.sh [--cases <list>] [--vendors <list>]

Run the pipeline benchmark suite. With no flags, every case runs for every
vendor (the previous default behaviour).

Options:
  --cases <list>     Comma- or space-separated pipeline cases to run.
                     Valid: ${ALL_CASES[*]}
                     Example: --cases pass-through,mask
  --vendors <list>   Comma- or space-separated vendors to run.
                     Valid: ${ALL_VENDORS[*]}
                     (red defaults to the latest stable released binary;
                     set RED_VERSION to pin a stable version)
                     Example: --vendors edgedelta,cribl
  --profile <name>  full (default) or short (pass-through validation; no release).
  --dry-run         Print the selected supported matrix without credentials or AWS.
  -h, --help         Show this help and exit.

Notes:
  * "passthrough" is accepted as an alias for "pass-through".
  * otelcol lookup and fluentbit regex mask are unsupported and skipped.
  * Prerequisite checks only run for the selected vendors.
EOF
}

# contains reports whether the first argument equals any of the remaining ones.
contains() {
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

is_vendor_selected() {
  contains "$1" "${SELECTED_VENDORS[@]}"
}

# vendor_supported_cases echoes the cases a given vendor can actually run.
vendor_supported_cases() {
  case "$1" in
    otelcol) echo "pass-through filter mask" ;;
    fluentbit) echo "pass-through filter lookup" ;;
    *)       echo "pass-through filter mask lookup" ;;
  esac
}

# cases_for echoes the selected cases that the given vendor supports, in
# canonical order. Empty output means "nothing to run for this vendor".
cases_for() {
  local vendor="$1"
  local supported
  supported=$(vendor_supported_cases "$vendor")
  local c out=()
  for c in "${ALL_CASES[@]}"; do
    if contains "$c" "${SELECTED_CASES[@]}" && contains "$c" $supported; then
      out+=("$c")
    fi
  done
  echo "${out[*]}"
}

# maybe_run executes the benchmark function only if its vendor is selected and
# at least one selected case applies to it.
maybe_run() {
  local vendor="$1" fn="$2"
  if ! is_vendor_selected "$vendor"; then
    echo "Skipping $vendor benchmark (vendor not selected)"
    return 0
  fi
  if [[ -z "$(cases_for "$vendor")" ]]; then
    echo "Skipping $vendor benchmark (no selected case applies; selected: ${SELECTED_CASES[*]})"
    return 0
  fi
  "$fn"
}

# parse_selection validates a comma/space-separated list against the allowed
# values for the given kind, normalises aliases, and writes the deduplicated
# result into the PARSED_SELECTION global array. It exits on invalid input.
PARSED_SELECTION=()
parse_selection() {
  local kind="$1" raw_list="$2"
  local -a allowed=()
  if [[ "$kind" == "cases" ]]; then
    allowed=("${ALL_CASES[@]}")
  else
    allowed=("${ALL_VENDORS[@]}")
  fi
  PARSED_SELECTION=()
  local raw v
  for raw in ${raw_list//,/ }; do
    v="$raw"
    [[ "$kind" == "cases" && "$v" == "passthrough" ]] && v="pass-through"
    if ! contains "$v" "${allowed[@]}"; then
      echo "Invalid $kind: '$raw' (valid: ${allowed[*]})" >&2
      exit 1
    fi
    contains "$v" "${PARSED_SELECTION[@]}" || PARSED_SELECTION+=("$v")
  done
  if [[ ${#PARSED_SELECTION[@]} -eq 0 ]]; then
    echo "No valid $kind selected" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cases)
      [[ -n "${2:-}" ]] || { echo "--cases requires a value" >&2; usage; exit 1; }
      parse_selection cases "$2"; SELECTED_CASES=("${PARSED_SELECTION[@]}"); shift 2 ;;
    --cases=*)
      parse_selection cases "${1#*=}"; SELECTED_CASES=("${PARSED_SELECTION[@]}"); shift ;;
    --vendors)
      [[ -n "${2:-}" ]] || { echo "--vendors requires a value" >&2; usage; exit 1; }
      parse_selection vendors "$2"; SELECTED_VENDORS=("${PARSED_SELECTION[@]}"); shift 2 ;;
    --vendors=*)
      parse_selection vendors "${1#*=}"; SELECTED_VENDORS=("${PARSED_SELECTION[@]}"); shift ;;
    --profile) BENCHMARK_PROFILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

export BENCHMARK_PROFILE="${BENCHMARK_PROFILE:-full}"
case "$BENCHMARK_PROFILE" in
  full) ;;
  short) SELECTED_CASES=("pass-through") ;;
  *) echo "Invalid benchmark profile: $BENCHMARK_PROFILE" >&2; exit 1 ;;
esac

echo "Selected vendors: ${SELECTED_VENDORS[*]}"
echo "Selected cases:   ${SELECTED_CASES[*]}"

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  for vendor in "${SELECTED_VENDORS[@]}"; do
    echo "$vendor: $(cases_for "$vendor")"
  done
  exit 0
fi

has_work=0
for vendor in "${SELECTED_VENDORS[@]}"; do
  [[ -z "$(cases_for "$vendor")" ]] || has_work=1
done
if [[ "$has_work" == 0 ]]; then
  echo "No supported scenarios selected; nothing to run."
  exit 0
fi

function check_prerequisites() {
  for cmd in terraform jq curl ssh scp python3 tar git; do
    command -v "$cmd" >/dev/null || { echo "Missing prerequisite: $cmd" >&2; exit 1; }
  done
  if is_vendor_selected red; then
    if [[ -n "${RED_BINARY:-}" ]]; then
      [[ -f "$RED_BINARY" ]] || { echo "RED_BINARY does not exist" >&2; exit 1; }
    elif [[ "${RED_BUILD_FROM_SOURCE:-0}" == 1 ]]; then
      [[ -f "${RED_SRC_DIR:-$git_root/../red}/Cargo.toml" ]] || { echo "Set RED_SRC_DIR for a source build" >&2; exit 1; }
    else
      local release_dir
      release_dir=$(mktemp -d "$git_root/.red-release.XXXXXX")
      python3 "$git_root/tools/fetch_red.py" "$release_dir"
      export RED_BINARY="$release_dir/red"
      export RED_RELEASE_METADATA="$release_dir/release.json"
    fi
  fi
  [[ -z "${ED_BINARY:-}" || -f "$ED_BINARY" ]] || { echo "ED_BINARY does not exist" >&2; exit 1; }
  if is_vendor_selected "edgedelta"; then
    # Edge Delta variables
    check_vars "ED_ORG_ID"
    [[ -n "${ED_API_TOKEN_CMD:-}" ]] || check_vars "ED_API_TOKEN"
  fi

  if is_vendor_selected "cribl"; then
    # Cribl variables
    check_vars "CRIBL_WORKSPACE" "CRIBL_ORG" "CRIBL_WORKER_GROUP" "CRIBL_CLIENT_ID" "CRIBL_CLIENT_SECRET" "CRIBL_LEADER_TOKEN"
  fi

}

function create_benchmark_environment() {
  if [[ "${BENCHMARK_PREBUILT_LOADGEN:-0}" == 1 ]]; then
    python3 "$git_root/tools/generator_bundle.py" verify "$git_root/.loadgen-build"
  else
    "$git_root/tools/build_generators.sh"
  fi
  echo "Creating benchmark resources..."
  create_benchmark_resources
  echo "Benchmark resources created successfully"
}

function prepare_for_benchmark() {
  runtime_dir=$(mktemp -d "$git_root/.runtime.XXXXXX")
  chmod 700 "$runtime_dir"
  export BENCHMARK_INSTANCE_ID=$(terraform -chdir="$git_root/aws_resources" output -raw instance_id)
  python3 "$git_root/tools/provenance.py" "$runtime_dir/provenance.json"
  cp -R "$git_root/pipelines" "$runtime_dir/pipelines"
  cp -R "$git_root/scripts" "$runtime_dir/scripts"
  update_s3_placeholder
  local topology="sequential agents on one instance; sequential scenarios and tiers; colocated loadgen"
  if [[ "${BENCHMARK_EXECUTION_MODE:-}" == parallel-agent-shard ]]; then
    topology="separate instance per agent; parallel agents; sequential scenarios and tiers; colocated loadgen"
  fi
  upload_folder_to_ec2_instance "$git_root/benchmark_scripts"
  upload_file_to_ec2_instance "$git_root/tools/capacity.py" "/home/ubuntu/benchmark_scripts/capacity.py"
  upload_file_to_ec2_instance "$git_root/tools/fixed.py" "/home/ubuntu/benchmark_scripts/fixed.py"
  upload_file_to_ec2_instance "$git_root/payloads/fixed-nginx.ndjson" "/home/ubuntu/benchmark_scripts/fixed-nginx.ndjson"
  python3 "$git_root/tools/aws_machine.py" "$BENCHMARK_INSTANCE_ID" "$runtime_dir/hardware-aws.json"
  upload_file_to_ec2_instance "$runtime_dir/hardware-aws.json" "/home/ubuntu/benchmark_scripts/hardware-aws.json"
  run_command_on_ec2_instance "mkdir -p /home/ubuntu/benchmark_scripts/benchmark_results && python3 /home/ubuntu/benchmark_scripts/collect_machine.py --topology '$topology' > /home/ubuntu/benchmark_scripts/benchmark_results/hardware.json && cp /home/ubuntu/benchmark_scripts/hardware-aws.json /home/ubuntu/benchmark_scripts/benchmark_results/hardware-aws.json && cp /home/ubuntu/benchmark_scripts/fixed-nginx.ndjson /home/ubuntu/benchmark_scripts/benchmark_results/fixed-nginx.ndjson"
  upload_file_to_ec2_instance "$runtime_dir/pipelines/lookup-benchmark.csv" "/tmp/lookup-benchmark.csv"
  run_command_on_ec2_instance "chmod 777 /tmp/lookup-benchmark.csv"
}

function cleanup_benchmark_environment() {
  local failed=0
  if [[ "$ed_benchmark" -eq 1 ]]; then
    (cd "$runtime_dir/pipelines/edgedelta" && ./edgedelta-api.sh delete) || failed=1
  fi
  if [[ "$cribl_benchmark" -eq 1 ]]; then
    (cd "$runtime_dir/pipelines/cribl" && ./cribl-api.sh cleanup-all) || failed=1
  fi
  if [[ "${BENCHMARK_EXTERNAL_AWS_CLEANUP:-0}" == 1 ]]; then
    echo "AWS cleanup delegated to the workflow after credential refresh."
  else
    echo "Destroying benchmark resources..."
    destroy_benchmark_resources || failed=1
  fi
  if [[ $failed != 0 ]]; then
    echo "Cleanup failed; retain aws_resources state and .runtime directory for recovery." >&2
  fi
  return "$failed"
}

function run_ed_benchmark() {
  echo "Running Edge Delta benchmark..."
  pushd "$runtime_dir/pipelines/edgedelta" > /dev/null
  ./edgedelta-api.sh create-base
  ed_benchmark=1
  PIPELINE_ID=$(cat pipeline_id.txt)
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' -e "s/{ED_API_KEY}/$PIPELINE_ID/g" "$runtime_dir/scripts/install_agent_ed.sh"
  else
    sed -i -e "s/{ED_API_KEY}/$PIPELINE_ID/g" "$runtime_dir/scripts/install_agent_ed.sh"
  fi
  echo "Installing Edge Delta agent..."
  run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_ed.sh"
  if [[ -n "${ED_BINARY:-}" ]]; then
    upload_file_to_ec2_instance "$ED_BINARY" /tmp/edgedelta-benchmark
    run_command_on_ec2_instance "sudo systemctl stop edgedelta; sudo install -m 0755 /tmp/edgedelta-benchmark /opt/edgedelta/agent/edgedelta"
  fi
  for type in $(cases_for edgedelta); do
    ./edgedelta-api.sh full $type.yaml
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark "edgedelta" $type
    done
  done
  popd > /dev/null
}

function run_red_benchmark() {
  echo "Running red (Edge Delta Rust agent) benchmark..."
  local red_src="${RED_SRC_DIR:-$git_root/../red}"
  if [[ -n "${RED_BINARY:-}" ]]; then
    echo "Uploading prebuilt red binary $RED_BINARY"
    upload_file_to_ec2_instance "$RED_BINARY" /tmp/red
  else
    if [[ ! -f "$red_src/Cargo.toml" ]]; then
      echo "red source not found at $red_src (set RED_SRC_DIR or RED_BINARY)" >&2
      exit 1
    fi
    echo "Packaging red source from $red_src"
    tar --exclude target --exclude .git --exclude .worktrees --exclude .env --exclude benchmark_results -czf "$runtime_dir/red-src.tgz" -C "$red_src" .
    upload_file_to_ec2_instance "$runtime_dir/red-src.tgz" /tmp/red-src.tgz
  fi
  echo "Installing red agent..."
  run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_red.sh"
  upload_folder_to_ec2_instance "$runtime_dir/pipelines/red"
  local red_bucket
  red_bucket=$(get_s3_bucket_name)
  for type in $(cases_for red); do
    run_command_on_ec2_instance "sudo cp /home/ubuntu/red/$type.yaml /etc/red/config.yaml"
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark "red" $type
      # Evidence that archives reached S3: red's own flush/upload log lines and,
      # when the aws CLI is available on the runner, the object count in the bucket.
      run_command_on_ec2_instance "sudo journalctl -u red.service --no-pager -n 400 | grep -E 'flushed object|s3 put_object|failed|panicked' | tail -n 12" || true
      if command -v aws >/dev/null 2>&1; then
        echo "S3 objects under edgedelta/ after red $type:"
        aws s3 ls "s3://$red_bucket/edgedelta/" --recursive --summarize 2>/dev/null | tail -n 2 || true
      fi
    done
  done
}

function run_cribl_benchmark() {
  echo "Running Cribl benchmark..."
  pushd "$runtime_dir/pipelines/cribl" > /dev/null

  cribl_benchmark=1
  export CRIBL_HTTP_INPUT_ID="pipeline_perf_http"
  export CRIBL_PIPELINE_ID="pipeline_perf_benchmark"
  export CRIBL_S3_OUTPUT_ID="pipeline_perf_s3"
  export CRIBL_ROUTE_ID="pipeline_perf_route"
  ./cribl-api.sh create-http-input
  S3_BUCKET=$(get_s3_bucket_name)
  export CRIBL_S3_BUCKET="$S3_BUCKET"
  ./cribl-api.sh create-s3-destination
  ./cribl-api.sh create-pipeline
  ./cribl-api.sh create-route
  cribl_benchmark=1
  ./cribl-api.sh agent-install > "$runtime_dir/scripts/install_agent_cribl.sh"
  upload_file_to_ec2_instance "$runtime_dir/scripts/install_agent_cribl.sh" /tmp/install_agent_cribl.sh
  run_command_on_ec2_instance "chmod +x /tmp/install_agent_cribl.sh"
  run_command_on_ec2_instance "sudo -E /tmp/install_agent_cribl.sh"

  for type in $(cases_for cribl); do
    ./cribl-api.sh update-pipeline $type.json
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark "cribl" $type
    done
  done
  # Release the shared worker-group configuration before measuring other agents.
  # If cleanup fails, the EXIT handler retries while the flag remains set.
  ./cribl-api.sh cleanup-all
  cribl_benchmark=0
  popd > /dev/null
}

function run_otelcol_benchmark() {
  echo "Running OpenTelemetry Collector benchmark..."
  echo "Installing OpenTelemetry Collector agent..."
  AGENT_ENV=$(resolve_agent_version otelcol) run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_otelcol.sh"
  upload_folder_to_ec2_instance "$runtime_dir/pipelines/otelcol"
  # No lookup scenario: OTel contrib has no shipped CSV lookup processor
  # (lookup is excluded automatically by cases_for).
  for type in $(cases_for otelcol); do
    run_command_on_ec2_instance "sudo cp /home/ubuntu/otelcol/$type.yaml /etc/otelcol-contrib/config.yaml"
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark "otelcol" $type
    done
  done
}

function run_bindplane_benchmark() {
  AGENT_ENV=$(resolve_agent_version bindplane) run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_bindplane.sh"
  upload_folder_to_ec2_instance "$runtime_dir/pipelines/bindplane"
  for type in $(cases_for bindplane); do
    run_command_on_ec2_instance "sudo cp /home/ubuntu/bindplane/$type.yaml /opt/observiq-otel-collector/config.yaml"
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark bindplane "$type"
    done
  done
}

function run_fluentd_benchmark() {
  echo "Running Fluentd benchmark..."
  echo "Installing Fluentd agent..."
  AGENT_ENV=$(resolve_agent_version fluentd) run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_fluentd.sh"
  upload_folder_to_ec2_instance "$runtime_dir/pipelines/fluentd"
  for type in $(cases_for fluentd); do
    run_command_on_ec2_instance "sudo cp /home/ubuntu/fluentd/$type.conf /etc/fluent/fluentd.conf"
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark "fluentd" $type
    done
  done
}


function run_vector_benchmark() {
  AGENT_ENV=$(resolve_agent_version vector) run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_vector.sh"
  upload_folder_to_ec2_instance "$runtime_dir/pipelines/vector"
  for type in $(cases_for vector); do
    run_command_on_ec2_instance "sudo cp /home/ubuntu/vector/$type.yaml /etc/vector/vector.yaml; sudo /usr/local/bin/vector validate --skip-healthchecks /etc/vector/vector.yaml"
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark vector "$type"
    done
  done
}

function run_fluentbit_benchmark() {
  run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_fluentbit.sh"
  upload_folder_to_ec2_instance "$runtime_dir/pipelines/fluentbit"
  run_command_on_ec2_instance "sudo cp /home/ubuntu/fluentbit/lookup.lua /etc/fluent-bit/lookup.lua"
  for type in $(cases_for fluentbit); do
    run_command_on_ec2_instance "sudo cp /home/ubuntu/fluentbit/$type.conf /etc/fluent-bit/fluent-bit.conf; sudo /opt/fluent-bit/bin/fluent-bit --dry-run -c /etc/fluent-bit/fluent-bit.conf"
    for BENCHMARK_MODE in capacity; do
      trigger_benchmark fluentbit "$type"
    done
  done
}

function download_benchmark_results() {
  date_tag=$(date +%Y%m%d_%H%M%S)
  mkdir -p "$git_root/benchmark_results/"
  download_folder_from_ec2_instance "/home/ubuntu/benchmark_scripts/benchmark_results/" "$git_root/benchmark_results/"
  mv "$git_root/benchmark_results/benchmark_results/" "$git_root/benchmark_results/$date_tag/"
  cp "$runtime_dir/provenance.json" "$git_root/benchmark_results/$date_tag/provenance.json"
  echo "Benchmark results downloaded successfully"
  python3 "$git_root/tools/summarize.py" "$git_root/benchmark_results/$date_tag"
}

function generate_versions_csv() {
  local csv_file="$git_root/benchmark_results/$date_tag/versions.csv"
  echo "agent,version" > "$csv_file"
  local vendor command version
  for vendor in "${SELECTED_VENDORS[@]}"; do
    [[ -n "$(cases_for "$vendor")" ]] || continue
    case "$vendor" in
      edgedelta) command='/opt/edgedelta/agent/edgedelta --version' ;;
      red) command='/opt/red/red --version' ;;
      cribl) command='/opt/cribl/bin/cribl version' ;;
      bindplane) command='/opt/observiq-otel-collector/observiq-otel-collector --version' ;;
      otelcol) command='otelcol-contrib --version' ;;
      fluentd) command='/opt/fluent/bin/fluentd --version' ;;
      vector) command='/usr/local/bin/vector --version' ;;
      fluentbit) command='/opt/fluent-bit/bin/fluent-bit --version' ;;
    esac
    version=$(ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o StrictHostKeyChecking=no -i "$git_root/aws_resources/ec2-benchmark-key.pem" "ubuntu@$INSTANCE_IP" "$command" 2>/dev/null | head -1) || version=unknown
    version=${version//\"/\"\"}
    printf '%s,"%s"\n' "$vendor" "${version:-unknown}" >> "$csv_file"
  done
}

finish() {
  local status=$?
  trap - EXIT
  set +e
  if [[ -n "${INSTANCE_IP:-}" && -z "${date_tag:-}" ]]; then
    download_benchmark_results
    generate_versions_csv
  fi
  if [[ -n "${date_tag:-}" && -d "$git_root/benchmark_results/$date_tag" ]]; then
    python3 "$git_root/tools/summarize.py" "$git_root/benchmark_results/$date_tag"
  fi
  cleanup_benchmark_environment
  local cleanup_status=$?
  if [[ $status == 0 ]]; then status=$cleanup_status; fi
  exit "$status"
}

check_prerequisites
trap finish EXIT
create_benchmark_environment
prepare_for_benchmark
maybe_run edgedelta run_ed_benchmark
maybe_run red run_red_benchmark
maybe_run cribl run_cribl_benchmark
maybe_run otelcol run_otelcol_benchmark
maybe_run fluentd run_fluentd_benchmark
maybe_run vector run_vector_benchmark
maybe_run fluentbit run_fluentbit_benchmark
maybe_run bindplane run_bindplane_benchmark
download_benchmark_results
generate_versions_csv
