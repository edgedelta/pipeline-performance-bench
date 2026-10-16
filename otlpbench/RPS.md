# Request-rate Pass-Through benchmark

This harness uses Rust for the load generator and destination. Python only orchestrates remote processes and records resource measurements; it is not in the telemetry path. Metrics Pass-Through is currently supported. The existing multi-scenario benchmark and public site remain separate.

Requests/sec and points/sec are distinct: `points/sec = requests/sec × points/request`. At 100,000 requests/sec, a batch of 1 offers 100,000 points/sec; a batch of 512 offers 51.2 million points/sec. Output requests are independently counted. In the matched-output mode, every output request must contain exactly the input batch size: 1 point in → 1 point out, or 512 points in → 512 points out. The sink records a distribution of output request sizes, not just an average.

## Run

```sh
cargo test --locked --manifest-path otlpbench/traffic-rs/Cargo.toml
cargo build --release --locked --manifest-path otlpbench/traffic-rs/Cargo.toml
python3 -m unittest otlpbench.test_rps -v
python3 -m otlpbench.cloud_rps --output otlp-rps-results \
  --rates 10000,100000 --batches 1,512 --seconds 60 \
  --connections 64 --concurrency 1024 --trials 1
python3 -m otlpbench.rps_chart otlp-rps-results/results.json /tmp/otlp-rps/index.html
python3 -m http.server 8766 --bind 127.0.0.1 --directory /tmp/otlp-rps
```

Use the existing Python requirements, Terraform, SSH, curl, tar, and authenticated AWS credentials. The cloud command provisions three c8i.8xlarge hosts in us-west-2: generator, agent, and sink. Traffic stays on private VPC addresses. OTLP ports are accessible only within the benchmark security group; SSH is restricted to the caller's address. `--instance-type` changes all three hosts. Run concurrent cloud jobs from separate checkouts because each checkout owns its Terraform state. The cloud command destroys its resources in `finally`, including failed benchmarks. Keep stdout/stderr as the run log.

The controller installs the pinned Rust build (or an explicit `--red-binary`), OTel Collector 0.162.0, and Bindplane 1.110.1 and runs them sequentially on the same agent host with fresh processes. It records binary versions and hashes. No merge or Pages deployment occurs.

## Matched output batching

The tested RED release forwards input batches through `otlp_output` without a configurable rebatching stage. The collectors therefore run without their `batch` processor; all three preserve input batch sizes. All agents receive OTLP/gRPC and export uncompressed OTLP/HTTP protobuf to the same sink. Collector retries and sending queues remain disabled. The collector HTTP connection and idle-pool limits are set to the configured concurrency (default 1,024) to avoid connection churn and ephemeral-port exhaustion when exporting one-point requests. See the [collector HTTP client settings](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.162.0/config/confighttp/client.go). Remote commands also raise the soft file-descriptor limit to 65,536 so the sink can accept the configured connection count. These limits are pool capacity, not a claim that every agent uses the same export concurrency. RED’s unrelated `item_buffer_flush_interval` and archive settings are omitted.

A warm-up gate and a measured-run gate inspect the entire request-size distribution. A mismatch is recorded as `batch_mismatch` and excluded from chart comparisons. Point counts and sums must still match. Matching output batches does not equalize every implementation detail, including acknowledgment behavior, exporter concurrency, resource metadata, or metric-object layout.

## Load and capacity accounting

- Persistent gRPC connections, no compression, an open-loop offered request schedule paced in 1 ms slices.
- Prepared protobuf bodies avoid reconstructing hundreds of point objects per request. Each request gets a distinct fixed-width `bench.batch` resource value without changing the protobuf layout. Metric values, attributes, and timestamps match the synthetic fixture.
- Configurable connections and maximum in-flight RPCs. A bounded per-worker queue prevents unlimited backlog. Requests that cannot be scheduled are counted as missed. Late completions are excluded from the achieved in-window request rate.
- Increasing concurrency may be required for a slow-acknowledging agent. For example, 100k requests/sec with 200 ms acknowledgment latency requires at least 20k simultaneous requests. A shortfall at a chosen concurrency is not proof of maximum vendor capacity.
- Calibration sends the same batch and rate directly from the generator to the Rust sink over gRPC. It must reach at least 95% of target with zero RPC errors/rejections and exact accepted/delivered point counts and sums. Failed calibration marks that case `harness_limited` and skips all vendor rankings.
- Calibration establishes ingress capacity, not every vendor's export shape. Agents export OTLP/HTTP protobuf to the Rust sink; the report includes output request/byte counts and sink CPU. An expanded output representation or export backpressure can still limit a vendor trial and needs separate diagnosis.
- A five-second readiness warm-up at up to 1,000 requests/sec is drained before counters reset. Each trial records input-window and through-delivery CPU independently. The latter includes final delivery drain. CPU windows include SSH control overhead; use longer trials to reduce its relative impact. RSS is a final snapshot, not a peak or average.
- Accepted input, rejected points, RPC errors, scheduled/missed requests, latency buckets, delivered output, and value sums remain in JSON. The fixture uses integer value 1, so its expected sum equals accepted points. No missing measurements are inferred.
- These are fixed-load measurements. They are neither a maximum-throughput search nor a production workload simulation. Repeat trials before interpreting small differences. A failed test can reflect client concurrency, ingress, export behavior, sink capacity, or network bandwidth.

## Standalone Rust commands

```sh
otlpbench/traffic-rs/target/release/otlp-traffic sink \
  --grpc-addr 127.0.0.1:14317 --http-addr 127.0.0.1:14318

otlpbench/traffic-rs/target/release/otlp-traffic load \
  --fixture otlp-rps-results/fixture-512.pb \
  --endpoint http://127.0.0.1:14317 --rps 100000 \
  --seconds 60 --connections 64 --concurrency 1024
```

The controller writes binary fixture files. `--sequence-offset` supports disjoint request IDs when manually distributing multiple generators; aggregate their counters and calibrate the combined load. Standalone commands bind loopback by default; expose them only on an isolated benchmark network. The sink accepts uncompressed OTLP protobuf over gRPC and HTTP, with 64 MiB message limits. It exposes local `/stats` and POST `/reset` controls; reset only after previous traffic has drained.

## Testing an unreleased Rust exporter

Pass `--red-binary /absolute/path/to/linux/red` to `otlpbench.cloud_rps` to install an optimized Linux build instead of the published release. Binary hashes remain in every measured row. Record its source commit alongside the report; the binary's release version alone does not identify a development build.

OTLP concurrency in the development agent follows incoming requests; no exporter worker-count setting is needed. Host SSH descriptor limits are configured by cloud-init, and remote processes use a soft limit of 65,536.

## Default Rust build

`cloud_rps` defaults to the measured automatic-concurrency build recorded in
[red-build.json](red-build.json), from Rust PR #20 (now merged). It checks the
local Linux binary's SHA-256 before provisioning cloud hosts and never silently
falls back to release 3.15.0. The default path assumes sibling `red` and
`pipeline-performance-bench` checkouts.

The pin identifies the tested PR source, not a stable release or the exact merged
main tree, which also contains other changes. Preserve this measured binary for
repeat comparisons. On another machine, supply a Linux x86_64 release binary
explicitly with `--red-binary /path/to/red`; rebuilding can produce a different
hash. Use the same explicit override to benchmark newer builds. Each run records
the actual binary hash in its results.

Use `--baseline-red-binary /path/to/prior/red` to rerun Rust on the same hosts after the three-vendor comparison. Baseline results and independent calibration are saved under `baseline/`; infrastructure is destroyed after both runs. The pinned default is preserved under the sibling Rust checkout’s `dist/benchmarks/` directory, separately from compiler outputs.

## Fixed-rate metric scenarios

```sh
python -m otlpbench.cloud_rps --output scenario-results \
  --scenarios pass-through,filter,enrich,aggregate,rollup,combined \
  --rates 10000 --batches 512 --seconds 30 --series-groups 64
```

Each scenario records separate calibration, configs, operation counters, and results.
The Rust generator cycles resource IDs over 64 groups so stateful processors see
recurring series. This changes resource cardinality from the earlier unique-ID
pass-through fixture; compare vendors within this run. No explicit collector batch
processor is added. Filtering produces 384 output points for each 512-point input;
aggregation and rollup use native reductions and do not require equal output batch
sizes. Resource metadata differences are permitted.

The sink verifies value sums, removed health points, enrichment, host-label removal,
and output reduction. Stateful scenarios start fresh without traffic warm-up and
allow up to 75 seconds for flushing. Report CPU cost as total CPU seconds through
delivery divided by the input window, so idle flush waits do not dilute cost.

Collector delta rollup behavior is verified from measured output counts and sums.
The v0.162.0 interval-processor README says delta metrics pass through, but its
[source implementation](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.162.0/processor/intervalprocessor/processor.go)
and these measurements show delta aggregation. Use the operation checks rather
than a documentation-based vendor exclusion.
