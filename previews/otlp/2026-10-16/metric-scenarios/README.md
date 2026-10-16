# Fixed-rate metrics scenarios

[Interactive report](index.html) · [Merged Rust PR #20](https://github.com/edgedelta/red/pull/20)

10,000 requests/sec, 512 points/request, 30 seconds of input per case, one trial. Three isolated c8i.8xlarge hosts, Rust generator and sink, OTLP/gRPC input, uncompressed OTLP/HTTP protobuf output. 64 connections, maximum 1,024 in-flight requests. Source build c7197c7 is the tested implementation from merged PR #20.

The workload repeats 64 resource groups, each with 64 host series, to permit stateful reduction without unbounded resource cardinality. This differs from the earlier pass-through fixture with a new resource ID for every request. All scenarios use the same bounded-series input. Timestamps and delta values follow the synthetic fixture; this is not a production workload simulation.

CPU cost is total agent CPU seconds through final delivery divided by input-window elapsed seconds. This includes delayed flush work without diluting it by an idle drain. Raw input-window and through-delivery measurements are retained. Stateful processors start fresh without a traffic warm-up; immediate processors receive a five-second warm-up. Stateful runs drain for up to 75 seconds.

Verification checks accepted value sums, expected filtered point counts, enrichment attributes, cardinality removal, and reduced output counts. Resource metadata differences are allowed. The collector README describes delta pass-through, but the [v0.162.0 implementation](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.162.0/processor/intervalprocessor/processor.go) and measured reduced point counts with preserved sums confirm delta aggregation. Initial documentation-based exclusions were corrected using recorded evidence; original labels remain in `initial_status` and unmodified per-scenario files.

| Scenario | Vendor | Reached req/s | CPU cost | Status |
|---|---|---:|---:|---|
| pass-through | red | 9999.3 | 8.046 | measured |
| pass-through | otelcol | 9999.3 | 5.358 | measured |
| pass-through | bindplane | 9999.7 | 5.780 | measured |
| filter | red | 6904.2 | 30.392 | input_shortfall |
| filter | otelcol | 9999.6 | 6.439 | measured |
| filter | bindplane | 9999.3 | 6.293 | measured |
| enrich | red | 5215.5 | 30.190 | input_shortfall |
| enrich | otelcol | 9999.2 | 7.699 | measured |
| enrich | bindplane | 9999.4 | 7.371 | measured |
| aggregate | red | 9999.3 | 13.743 | measured |
| aggregate | otelcol | 9999.3 | 15.872 | measured |
| aggregate | bindplane | 9998.6 | 15.199 | measured |
| rollup | red | 9999.4 | 14.717 | measured |
| rollup | otelcol | 2682.3 | 1.738 | input_shortfall |
| rollup | bindplane | 2692.1 | 1.780 | input_shortfall |
| combined | red | 9999.3 | 13.641 | measured |
| combined | otelcol | 5088.5 | 8.724 | input_shortfall |
| combined | bindplane | 3373.1 | 6.895 | input_shortfall |

All 18 cases passed final operation and delivery verification. Six cases had input throughput shortfalls. All seven temporary infrastructure resources were destroyed. The public site was not changed.
