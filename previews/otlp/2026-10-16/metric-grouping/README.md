# OTLP metric grouping comparison

[Interactive report](index.html) · [Rust PR #20](https://github.com/edgedelta/red/pull/20)

Fresh comparison on three isolated c8i.8xlarge hosts, 30 seconds per trial, 64 input connections, 1,024 maximum in-flight requests. Rust generator and sink. All agents receive OTLP/gRPC and export uncompressed OTLP/HTTP protobuf. Exact output-batch sizes and accepted point counts/sums are verified.

After: c7197c7 (PR #20). Before: d09072d (previous measured PR #19 build). Both Rust builds ran sequentially on the same hosts. The newer build also includes intervening main changes, so this comparison does not isolate grouping from every other change. One trial per case; small differences need repetition.

| Build | Points/request | Offered req/s | Reached req/s | CPU cores | Output bytes/request | Status |
|---|---:|---:|---:|---:|---:|---|
| Edge Delta Rust (new) | 1 | 10000 | 9999.7 | 0.612 | 345 | measured |
| otelcol | 1 | 10000 | 9999.7 | 1.957 | 172 | measured |
| bindplane | 1 | 10000 | 9999.8 | 1.949 | 172 | measured |
| Edge Delta Rust (new) | 1 | 100000 | 99701.2 | 5.873 | 345 | measured |
| otelcol | 1 | 100000 | 99747.7 | 14.588 | 172 | measured |
| bindplane | 1 | 100000 | 99837.8 | 15.019 | 172 | measured |
| Edge Delta Rust (new) | 512 | 10000 | 9999.5 | 7.879 | 30803 | measured |
| otelcol | 512 | 10000 | 9999.4 | 5.439 | 30630 | measured |
| bindplane | 512 | 10000 | 9999.6 | 5.101 | 30630 | measured |
| Edge Delta Rust (new) | 512 | 100000 | — | — | — | harness_limited |
| otelcol | 512 | 100000 | — | — | — | harness_limited |
| bindplane | 512 | 100000 | — | — | — | harness_limited |
| Edge Delta Rust (prior) | 1 | 10000 | 9999.7 | 0.616 | 345 | measured |
| Edge Delta Rust (prior) | 1 | 100000 | 99843.5 | 5.971 | 345 | measured |
| Edge Delta Rust (prior) | 512 | 10000 | 9999.0 | 11.910 | 44596 | measured |
| Edge Delta Rust (prior) | 512 | 100000 | — | — | — | harness_limited |

Library tests: 1,246 passed, one ignored. Four delivery integration tests passed. PR #20 remains unmerged; public Pages is unchanged. Raw captures, configs, calibration, warm-up evidence, and generator source are retained.
