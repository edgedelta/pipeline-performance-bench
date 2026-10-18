# Trace Filter and Sample optimization

Rust candidate `2e709b3` versus OpenTelemetry Collector 0.162.0 and Bindplane 1.110.1. Open `index.html` for the interactive report. This report supplements the original trace ladder; Pass-Through, Mask and Tail were not rerun here.

## Confirmation

Two 60-second trials per agent and scenario, with reversed vendor order relative to the initial comparison. All agents receive 8,000 requests/sec × 512 spans/request (4.096 million spans/sec), using 64 connections and up to 1,024 outstanding requests. Load, agent and sink run on separate c8i.8xlarge instances. Input is OTLP/gRPC; output is uncompressed OTLP/HTTP for every agent.

| Scenario | Rust CPU cores | OTel CPU cores | Bindplane CPU cores | Rust reduction vs OTel |
|---|---:|---:|---:|---:|
| Filter | 8.440 | 8.714 | 8.714 | 3.1% |
| Sample | 8.439 | 13.408 | 13.062 | 37.1% |

CPU is cumulative agent CPU through final delivery divided by the configured 60-second load window (`through_delivery.cpu_seconds / load.seconds`), not elapsed drain time. Memory values in raw data are final RSS. These are results for this workload and tested rate, not maximum-capacity estimates.

Filter removes the health route (25%) and checks exact output count, payload fields, parent/child pairing and output batch size (384 spans). Sample uses each agent’s native 50% trace-ID sampling and verifies retention, payload and matching parent/child fingerprints. Sample does not independently prove the exact retained set or exclude small delivery loss; `sampling_verified` is separate from `delivery_verified`. Native sample output batch sizes vary. Each input request contains 256 complete two-span traces with unique IDs across requests and stable resource metadata. Mixed metadata is covered by correctness tests, not this throughput fixture.

## Iterations

| Candidate | Filter req/sec | Filter CPU | Sample req/sec | Sample CPU |
|---|---:|---:|---:|---:|
| e12daf8 baseline | 3560.3 | 32.073 | 4287.3 | 32.065 |
| Native evaluation | 6101.5 | 32.040 | 7999.4 | 24.084 |
| 7c7ff0b borrowed encoding | 7999.6 | 10.037 | 7999.7 | 9.062 |
| 8b3bdfc temporary allocations | 7999.6 | 9.578 | 7999.6 | 8.760 |
| 813620c in-place processing | 7999.6 | 9.446 | 7999.7 | 8.680 |
| c4bbadb binary IDs | 7999.6 | 8.854 | 7999.6 | 8.573 |
| 1a85b09 static kind/status | 7999.7 | 8.709 | 7999.7 | 8.367 |
| 2e709b3 direct comparisons | 7999.7 | 8.448 | 7999.6 | 8.447 |

The baseline exhausted approximately 32 cores without sustaining the target. Individual development iterations have one trial; use the repeated confirmation above for the final comparison.

## Implementation and profiling

- Evaluate supported trace filter conditions with a read-only native field view, avoiding full span/event/link context reconstruction. Other conditions retain the full context fallback.
- Compare direct attribute/resource conditions without building even the temporary field view, preserving precedence and short-circuit semantics.
- Encode trace-only HTTP OTLP exports directly from borrowed fields, with generated-protobuf equivalence tests and mixed resource/scope grouping.
- Share resource maps and move decoded attributes into native spans.
- Process unary stages in place within each batch; splitting, aggregation and conditional stages retain their applicable fallback behavior.
- Preserve OTLP trace/span/link IDs as binary until a condition or text destination needs hexadecimal. Sampling uses the unchanged text representation and produces identical decisions.
- Share static span-kind/status names while preserving custom values, serialization and mutation isolation.

No workload-specific processor settings or worker-count knobs were added.

The initial profile was dominated by allocation/freeing, map copies and context conversion. After borrowed encoding, profiles shifted toward protobuf decoding and remaining allocation/freeing. The binary-ID profile still spent roughly 30% in allocation/freeing, motivating static kind/status storage. Profiles are separate, unscored 15-second loads collected with perf cpu-clock at 99 Hz and DWARF stacks; profiling never overlaps scored trials.

Microbenchmarks compare isolated changes on the same agent host. Native filtering reduced full-context work from about 5.3 μs to 0.2 μs/span, then direct attribute comparisons reduced the condition to about 33 ns/span; borrowed encoding reduced about 1.85 μs to 0.36 μs/span. In-place processing reduced the isolated batch stage from about 280 ns to 170 ns/span, then direct conditions lowered it to about 110 ns/span. Decode plus conversion declined from about 1,180 ns before binary IDs to 1,115 ns with IDs and 1,020 ns with shared kind/status strings. The microbench executable uses the system allocator; production uses mimalloc. Full scenarios decide the performance result.

## Evidence

Raw trials, calibrations, fixtures, exact vendor YAML, agent logs, microbenchmark output, readable profiles, source hashes and Rust generator/sink source archive are included. `source.json` maps candidate commits to binary SHA-256 hashes. Native-only is represented by its patch against e12daf8; later candidates are committed in Rust PR #21.

Validation: library suite passed (1,264 tests, six ignored), including static-storage/serialization coverage, seven native processor integration tests passed, 17 other integration tests passed, 32 Python smoke tests passed, and all-target Clippy passed with existing warnings. Browser rendering and every chart iteration/measure were checked.

Draft PRs remain unmerged. The public Pages site is unchanged.
