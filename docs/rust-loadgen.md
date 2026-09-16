# Rust load generator and Go comparison

The existing Go tool has two workload modes. Legacy throughput tests generate NGINX-like records and send as fast as the configured workers allow. Fixed-rate tests replay `payloads/fixed-nginx.ndjson`: one JSON log per HTTP POST, with a single global rate budget shared by all workers. Workers reuse HTTP connections and wait for each response before taking another log. Both modes measure acknowledged HTTP ingestion, not verified durable delivery.

`loadgen-rust` implements the fixed-rate HTTP/1 path using Tokio and Hyper. The daily workflow uses Rust workers for fixed-rate tiers, sustained-throughput searches and their calibration. Go is retained for explicit legacy/local comparisons and process monitoring; the Rust tool does not implement those modes or HTTPS/proxy support. The Rust binary accepts the existing fixed-rate flags plus `--runtime-threads` to control runtime worker threads.

## Matching behavior

- Identical corpus bytes and SHA-256, one log per request, 256 concurrent workers by default; no batching or compression.
- One global scheduler, 1ms ticks, at most 5ms catch-up budget, bounded worker queue. Scheduling misses, queue drops and expired work stay separate.
- Offered counts only logical requests fully written inside the measurement window. Retries cannot inflate offered counts. Acknowledged requires a response below HTTP 400 and complete response body inside the window; late acknowledgments are separate. Redirects are recorded, not followed; the benchmark validator rejects them as invalid configuration.
- Up to two fresh-connection retries on qualifying connection failures before response headers, with 10/20ms backoff inside the original request timeout. `--retry-ambiguous` explicitly permits retries after writes, with possible duplicates. HTTP rejection, timeouts and truncated response bodies do not trigger these retries.
- SIGINT/SIGTERM cancels work and retains canceled/partial JSON; drain waits for outstanding requests. HTTP drain is not an agent backlog measurement.
- Separate warm-up and measurement phases. JSON schema 2 works with `tools/fixed.py`; generator CPU is process user+system time, generator memory is Linux RSS. Optional `--fixed-cgroup` samples the agent's cgroup v2 CPU and memory. Unavailable measurements remain null.

The HTTP libraries and runtime scheduling differ, as do User-Agent headers. Go's HTTP transport can transparently recover some idle-connection failures internally; Rust reconnects closed senders and otherwise uses explicit retries. These implementations cannot guarantee identical internal transport events for every race, so compare final outcomes and retain raw retry/ambiguity counters.

## Build and validate

```sh
cargo test --locked --manifest-path loadgen-rust/Cargo.toml
cargo build --locked --release --manifest-path loadgen-rust/Cargo.toml
python3 tests/loadgen_protocol.py loadgen-rust/target/release/pipeline-loadgen-rust
```

Protocol tests exercise actual HTTP exchanges: keep-alive, server-requested closure, chunked bodies, ambiguous connection failures/recovery, exhausted retries, HTTP 429/503/400/302, truncated response bodies, late acknowledgments, cancellation and a global rate across multiple workers. On non-Linux hosts RSS is unavailable; use the Docker comparison for resource measurements.

## Reproduce the local side-by-side comparison

Prerequisites: Go, Docker with at least eight available Linux vCPUs, and network access for pinned source/dependencies/images during build. No AWS resources or releases are created.

```sh
./tools/compare_loadgens_local.sh
# Longer measurement windows, same rate tiers:
./tools/compare_loadgens_local.sh --seconds 60 --warmup 10 --repeats 3
```

The wrapper builds the existing pinned/patched Go implementation and Rust release binary for Docker's native architecture, validates both against the same fault fixtures, then runs 25k, 75k, 100k and 200k logs/sec. It allocates four logical CPUs to the external Go acknowledgment receiver and four different CPUs to the generator; both run in one Linux VM/container. `GOMAXPROCS=4` and Rust runtime threads=4. Generators run sequentially in alternating order, with a fresh receiver per trial. Default: 2s warm-up, 15s measurement, three repeats. This is a local calibration comparison, not the daily agent suite.

`benchmark_results/loadgen-comparison-*/` contains raw per-trial JSON, logs, `data.json`, `report.md`, Go source/build provenance, and image identities. `tools/compare_loadgens.py` validates both generators with the same existing phase/accounting/resource parser and independently checks receiver request totals. Invalid trials remain explicit and fail the comparison command. A target shortfall remains measured evidence, not an invalid run or an agent-capacity conclusion.

Reported CPU/log and throughput/MB use acknowledged logs/sec and generator-only process measurements. CPU 100% means one logical core; MB means 1,000,000 bytes. Lower absolute CPU or memory is not an equal-throughput win when the target is missed. CPU affinity in a VM does not pin physical performance/efficiency cores or eliminate host contention. No language-wide conclusion or extrapolated 100k/200k result should be drawn from the daily 75k measurements.

## Task-per-request Tokio dispatcher

Select `--dispatch-mode tasks --max-inflight 256 --pending-capacity 256` to use the second Rust design. The global pacer admits one bounded Tokio task per scheduled request. A semaphore caps active HTTP operations; a separate admission semaphore caps total active + waiting tasks at `max-inflight + pending-capacity`. No fixed worker pool is started. `--workers` is unused in this mode and is null in its JSON metadata. `--runtime-threads` still controls runtime threads.

Tasks reuse a bounded pool of idle HTTP/1 connections. Both Rust dispatchers call the same send/retry/acknowledgment implementation. Completed task results are reaped on scheduler ticks, and all remaining tasks are drained at phase end. Tasks waiting beyond the measurement deadline expire without sending. Exhausted admission capacity is recorded as `admission_dropped_logs`, also exposed under the legacy `worker_queue_dropped_logs` field for accounting compatibility; these are aliases, not additive counters. No HTTP requests are retried because of local admission failure.

`pending-capacity=0` provides no additional admission buffer. The cap still applies to tasks that have been admitted but have not yet been polled by Tokio. Consequently, a sudden scheduling burst can be rejected before all HTTP slots become busy. This is measured explicitly instead of allowing unlimited waiting tasks.

Compare all three implementations on a fresh local run:

```sh
./tools/compare_loadgens_local.sh --include-tasks --rates 75000,100000,200000 --workers 256 --warmup 5 --seconds 15 --repeats 3
```

For equal limits, Go and Rust workers each have 256 active senders and 256 pending queue slots; Rust tasks have 256 HTTP permits and 256 additional admission slots. Task buffering can be changed independently with `--task-pending-capacity`, and any change is recorded in the report. The three-way run rotates execution order so each implementation runs first, second and third once per rate. It measures every implementation again rather than mixing historical measurements with a new result. This remains a local experiment; it does not change the daily agent benchmark or its publication policy.

## Daily build and deployment

The daily workflow builds both generators once in a shared Ubuntu 24.04 x86_64 job before any EC2 provisioning. Cargo uses the committed lockfile and Rust 1.98.0; dependency and release-build caches are reused. Each agent downloads the same bundle, verifies source and executable checksums, and uploads the binaries to EC2. No Rust compiler is installed on benchmark instances. Build failures stop the suite before AWS resources are created.

Fixed tiers and calibration explicitly select `loadgen-rust --dispatch-mode workers --workers 256`. Tokio uses the available CPU count; no new CPU affinity or thread restriction is applied. Rates, corpus, warm-up, timing, retries, agent measurements and shortfall handling remain the same. Fixed-generator build identity is retained under `provenance.fixed_rate.generator`; combining different builds or dispatch modes is rejected. Historical Go measurements remain readable without inventing Rust metadata.

For direct runs, build on Ubuntu 24.04 x86_64 with Go 1.26.0 and `rustup toolchain install 1.98.0 --profile minimal`, then use `./run.sh`. Alternatively, extract a matching CI generator artifact into `.loadgen-build` and set `BENCHMARK_PREBUILT_LOADGEN=1`; checksum/source validation still runs before provisioning. This environment variable never downloads or trusts an unrelated release binary.

Observed local release compilation took approximately 8–17 seconds; clean toolchain/dependency downloads add time. GitHub runner build timing has not yet been measured. Compilation happens once per workflow, outside the measured workload and before billable EC2 runtime.

The daily target set is 10k, 25k, 50k, 75k and 125k logs/sec (run provenance schema 3). Raw per-tier JSON remains schema 2. Historical schema-2 suites retain four tiers. The new tier runs last and is skipped after an earlier measured shortfall; release tables list it first.

## Short AWS validation before a full run

The workflow `profile` input accepts `short` or `full` (default; scheduled jobs remain full). Short mode uses all selected agents but only pass-through and Rust fixed-rate targets 10k and 125k. In schema 4, those measurements also supply the throughput summary; no Go sweep or extra capacity probes run. Fixed rates retain the full 10-second warm-up, 60-second measurement and 60-second post-load observation, plus stable startup, so the check still exercises connection rotation. Higher rates retain the normal skip-after-shortfall policy. Calibration runs at both rates. Instance types, payload, retry policy and cleanup are unchanged. Typical duration is approximately 8–12 minutes, dependent on provisioning and startup.

Short reports are explicitly labeled and retained only as workflow artifacts; both the workflow and publisher prohibit a short-run release. The short gate requires complete evidence, Rust passing 10k, and no final Rust request errors at measured fixed-rate tiers. Genuine capacity shortfalls for other agents remain visible and do not imply an infrastructure failure. This gate does not establish long-term reliability or test filter/mask/lookup pipelines.

```
gh workflow run benchmark.yml --repo edgedelta/pipeline-performance-bench --ref main -f profile=short
# After reviewing the successful short-run measurements and cleanup:
gh workflow run benchmark.yml --repo edgedelta/pipeline-performance-bench --ref main -f profile=full
```

Rust loadgen 0.1.1 waits for Hyper connection readiness and safely retries a canceled dispatch only before response headers and before any request bytes were written. Actual application cancellation, timeout, HTTP rejection and incomplete response body policies remain unchanged. Each phase retains up to eight attempt diagnostics and eight separately retained final-error diagnostics in raw JSON, without request payloads or headers.

Schema-4 full suites also use Rust workers for the [sustained-throughput search](fixed-throughput.md#rust-sustained-throughput-search-schema-4). The old Go sweep remains an explicit legacy command only.
