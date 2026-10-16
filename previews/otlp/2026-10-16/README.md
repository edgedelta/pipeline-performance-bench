# OTLP PR benchmark results — 2026-10-16

These results were run from the unmerged [PR #29](https://github.com/edgedelta/pipeline-performance-bench/pull/29) checkout on isolated Ubuntu `c8i.2xlarge` instances. The public log benchmark was not updated.

- [Full report and resource-cost tables](report.md)
- [Interactive preview](report.html) — download and open locally; includes signal, scenario, and offered-rate selectors
- [Raw evidence archive](evidence.tar.gz) — configurations, sent/received correctness fixtures, calibrations, measurements, versions, binary hashes, and run commits
- [Merged JSON results](data)

The suite defines six metrics scenarios and seven traces scenarios across eight agents. **31 configurations passed the correctness fixture, 38 failed the configured contract, and 35 have no completed adapter.** The passing configurations produced **61 verified fixed-load measurements and one output-count mismatch** across the 1k/10k input-rate trials. Missing adapters and failed candidate configurations are not proof of unsupported vendor capabilities.

These are preliminary resource costs at fixed offered rates, not maximum-throughput rankings: 512 points/spans per request, four persistent OTLP/gRPC clients, no compression, five seconds of warm-up, and 30 seconds of measured input. Whole batches give approximately 9,984 accepted items/sec at the nominal 10k rate. Input uses one delta-sum metric workload or two-span traces. Broader metric types, batch-size sweeps, repeated trials, and end-to-end latency remain outside this initial preview.

## Findings to review before merging

- **Edge Delta:** Point/span counts generally survive, but the strict preservation contract catches resource/scope changes. Rust also encodes an empty root parent as an all-zero ID; Go drops metric start timestamps and changes span kind/timestamp precision. The configured Rust Sample case retains no spans. These cases receive no performance score. Trace IDs were preserved in the forwarding fixtures.
- **Aggregate / Rollup / Combined:** OTel and Bindplane's tested configurations do not implement the specified cross-request, aligned event-time aggregation. After a full 70-second drain, Rollup produces 64 points instead of 128 and Combined produces 2 instead of 4. Rust produces the expected reduced counts but still fails strict metadata fidelity. Alternative equivalent configurations need validation before comparing their performance.
- **Sampling:** OTel and Bindplane pass after allowing the standard OTel sampling member in `tracestate`; whole-trace completeness and payload preservation are still checked.
- **Span-to-metrics:** OTel and Bindplane pass both correctness and measured-window counter checks. At nominal 10k input, each converts 299,520 accepted spans into 299,520 calls/histogram observations, with 37,440 error spans and the expected latency sum.
- **Fluent Bit:** Forwarding and several trace cases pass. Its tested metric-enrichment configuration changes metric temporality/metadata and collapses the fixture. Tail passes the small fixture and 1k run, but the 10k trial delivers 74,890 spans where 74,880 are expected; this is an excess-count mismatch, not a throughput result.
- **Cribl:** Metrics forwarding passes. Trace forwarding changes nanosecond timestamps. The initial transformation adapters do not yet make the requested changes and need adapter work; their failures should not be read as a vendor support determination.
- **Vector / Fluentd:** Metrics and traces forwarding pass. Further scenario adapters remain to be implemented and verified.

## Provenance and execution

Each merged scenario records its exact benchmark commit, binary hash, and version. `source_runs` retains each run's calibration. The evidence archive preserves the original outputs before merging targeted rechecks; the display label `delivery_mismatch` also covers the earlier runner's `delivery_shortfall` flag when actual output exceeds expected output.

The existing GitHub Actions AWS role trusts only `main`. The cloud runs therefore used the PR checkout and existing local AWS access, without widening that shared role. The PR workflow can run the same artifact-only suite once branch execution is authorized separately. Normal PR validation runs independently.

The PR stays draft. No release, Pages update, or merge was performed.
