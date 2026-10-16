# Automatic OTLP export concurrency

[Interactive report](index.html) · [Rust PR #19](https://github.com/edgedelta/red/pull/19)

Rust OTLP output preserves incoming request concurrency without an exporter worker-count setting. Each caller awaits delivery. HTTP connections are reused; gRPC channel reuse is also implemented and tested, although this benchmark uses HTTP output. Persistent queues and circuit breakers retain serial behavior.

Three isolated c8i.8xlarge hosts; Rust generator and sink; OTLP/gRPC input and uncompressed OTLP/HTTP protobuf output; 64 persistent input connections; at most 1,024 in-flight generator requests; 30 seconds per measured trial. Output batches must exactly match input sizes and accepted point counts/sums must be delivered. The collector HTTP pools have capacity for 1,024 connections; their sending queues, retries, and batch processors are disabled.

The gray bar is the published Rust 3.15.0 release, freshly measured on the same hosts. The green bar is unreleased source commit `d09072d45412da792af635ccd8f2557ba6547940`. This is a release comparison: the development branch also includes changes already on main, so the entire speedup cannot be attributed solely to this PR. No vendor scores are assigned when harness calibration fails.

| Vendor/build | Points/request | Offered requests/sec | Reached requests/sec | CPU cores | Status |
|---|---:|---:|---:|---:|---|
| Rust PR #19 | 1 | 10,000 | 9,999 | 0.613 | measured |
| Rust 3.15.0 release | 1 | 10,000 | 3,752 | 0.295 | input_shortfall |
| OTel Collector | 1 | 10,000 | 9,999 | 1.730 | measured |
| Bindplane | 1 | 10,000 | 10,000 | 1.756 | measured |
| Rust PR #19 | 1 | 100,000 | 99,755 | 6.069 | measured |
| Rust 3.15.0 release | 1 | 100,000 | 2,641 | 0.226 | input_shortfall |
| OTel Collector | 1 | 100,000 | 99,838 | 15.184 | measured |
| Bindplane | 1 | 100,000 | 99,863 | 15.651 | measured |
| Rust PR #19 | 512 | 10,000 | 9,999 | 11.927 | measured |
| Rust 3.15.0 release | 512 | 10,000 | 671 | 0.777 | input_shortfall |
| OTel Collector | 512 | 10,000 | 10,000 | 5.277 | measured |
| Bindplane | 512 | 10,000 | 9,999 | 5.527 | measured |
| Rust PR #19 | 512 | 100,000 | — | — | harness_limited |
| Rust 3.15.0 release | 512 | 100,000 | — | — | harness_limited |
| OTel Collector | 512 | 100,000 | — | — | harness_limited |
| Bindplane | 512 | 100,000 | — | — | harness_limited |

All measured rows passed exact output-batch and accepted-point delivery checks. CPU includes the final delivery drain and SSH control overhead. These are fixed-load measurements, not maximum-capacity claims. Raw results include RPC errors, latency buckets, binary hashes, and calibration records.

`measured-results.json` contains the new three-vendor run; `released-baseline/results.json` contains the independently calibrated release baseline. `results.json` combines them for the visual report. Configurations, fixtures, warm-up evidence, bounded logs, and the measured Rust traffic-generator source are retained.

Validation: 116 Rust output tests and four focused integration tests passed. Both PRs remain unmerged; the public Pages site is unchanged.
