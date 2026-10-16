# OTLP metrics and traces — PR preview

Exploratory fixed-rate run: 512 items/request, four persistent OTLP/gRPC clients, no compression. Native OTLP/HTTP output to a local destination. These are not maximum-capacity rankings. Correctness failures have no performance score.

| Agent | Version |
|---|---|
| Edge Delta (Rust) | red 3.15.0 |
| Edge Delta (Go) | Agent version: v2.27.0-rc.19, commit hash: 81068f9455006f841310f35ce0edda84cc8c4b17, built on: Fri Oct 16 17:31:12 UTC 2026 |
| Bindplane (Dynatrace) | observiq-otel-collector version v1.110.1 |
| OpenTelemetry Collector | otelcol-contrib version 0.162.0 |
| Cribl | Software Version: 4.20.2-7199aa90 |
| Vector (Datadog) | vector 0.59.0 (x86_64-unknown-linux-gnu a3231c7 2026-10-06 13:52:51.733983360) |
| Fluent Bit | Fluent Bit v5.1.4 |
| Fluentd | fluentd 1.19.4 |

## Forwarding at 10k input items/sec

| Agent | Metrics CPU cores | Metrics RSS MB | Traces CPU cores | Traces RSS MB |
|---|---:|---:|---:|---:|
| Edge Delta (Rust) | — | — | — | — |
| Edge Delta (Go) | — | — | — | — |
| Bindplane (Dynatrace) | 0.018 | 217.096 | 0.025 | 224.454 |
| OpenTelemetry Collector | 0.017 | 221.206 | 0.024 | 226.819 |
| Cribl | 0.245 | 1425.798 | — | — |
| Vector (Datadog) | 0.184 | 152.790 | 0.300 | 165.228 |
| Fluent Bit | 0.056 | 22.890 | 0.059 | 27.659 |
| Fluentd | 0.058 | 189.152 | 0.118 | 355.109 |

A dash means no validated measurement. These are fixed-load resource costs, not capacity rankings.

## All scenarios

| Signal | Scenario | Agent | Result | Accepted/s at 10k | CPU cores | RSS MB |
|---|---|---|---|---:|---:|---:|
| metrics | Pass-Through | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| metrics | Pass-Through | Edge Delta (Go) | semantic_mismatch | — | — | — |
| metrics | Pass-Through | Bindplane (Dynatrace) | measured | 9,983.97 | 0.02 | 217.10 |
| metrics | Pass-Through | OpenTelemetry Collector | measured | 9,983.94 | 0.02 | 221.21 |
| metrics | Pass-Through | Cribl | measured | 9,983.97 | 0.24 | 1,425.80 |
| metrics | Pass-Through | Vector (Datadog) | measured | 9,983.97 | 0.18 | 152.79 |
| metrics | Pass-Through | Fluent Bit | measured | 9,983.95 | 0.06 | 22.89 |
| metrics | Pass-Through | Fluentd | measured | 9,983.97 | 0.06 | 189.15 |
| metrics | Filter | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| metrics | Filter | Edge Delta (Go) | semantic_mismatch | — | — | — |
| metrics | Filter | Bindplane (Dynatrace) | measured | 9,983.97 | 0.02 | 220.27 |
| metrics | Filter | OpenTelemetry Collector | measured | 9,983.93 | 0.02 | 220.09 |
| metrics | Filter | Cribl | semantic_mismatch | — | — | — |
| metrics | Filter | Vector (Datadog) | not_configured | — | — | — |
| metrics | Filter | Fluent Bit | not_configured | — | — | — |
| metrics | Filter | Fluentd | not_configured | — | — | — |
| metrics | Enrich | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| metrics | Enrich | Edge Delta (Go) | semantic_mismatch | — | — | — |
| metrics | Enrich | Bindplane (Dynatrace) | measured | 9,983.96 | 0.02 | 221.67 |
| metrics | Enrich | OpenTelemetry Collector | measured | 9,983.95 | 0.02 | 223.88 |
| metrics | Enrich | Cribl | semantic_mismatch | — | — | — |
| metrics | Enrich | Vector (Datadog) | not_configured | — | — | — |
| metrics | Enrich | Fluent Bit | semantic_mismatch | — | — | — |
| metrics | Enrich | Fluentd | not_configured | — | — | — |
| metrics | Aggregate | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| metrics | Aggregate | Edge Delta (Go) | semantic_mismatch | — | — | — |
| metrics | Aggregate | Bindplane (Dynatrace) | semantic_mismatch | — | — | — |
| metrics | Aggregate | OpenTelemetry Collector | semantic_mismatch | — | — | — |
| metrics | Aggregate | Cribl | not_configured | — | — | — |
| metrics | Aggregate | Vector (Datadog) | not_configured | — | — | — |
| metrics | Aggregate | Fluent Bit | not_configured | — | — | — |
| metrics | Aggregate | Fluentd | not_configured | — | — | — |
| metrics | Rollup | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| metrics | Rollup | Edge Delta (Go) | semantic_mismatch | — | — | — |
| metrics | Rollup | Bindplane (Dynatrace) | semantic_mismatch | — | — | — |
| metrics | Rollup | OpenTelemetry Collector | semantic_mismatch | — | — | — |
| metrics | Rollup | Cribl | not_configured | — | — | — |
| metrics | Rollup | Vector (Datadog) | not_configured | — | — | — |
| metrics | Rollup | Fluent Bit | not_configured | — | — | — |
| metrics | Rollup | Fluentd | not_configured | — | — | — |
| metrics | Combined | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| metrics | Combined | Edge Delta (Go) | semantic_mismatch | — | — | — |
| metrics | Combined | Bindplane (Dynatrace) | semantic_mismatch | — | — | — |
| metrics | Combined | OpenTelemetry Collector | semantic_mismatch | — | — | — |
| metrics | Combined | Cribl | not_configured | — | — | — |
| metrics | Combined | Vector (Datadog) | not_configured | — | — | — |
| metrics | Combined | Fluent Bit | not_configured | — | — | — |
| metrics | Combined | Fluentd | not_configured | — | — | — |
| traces | Pass-Through | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| traces | Pass-Through | Edge Delta (Go) | semantic_mismatch | — | — | — |
| traces | Pass-Through | Bindplane (Dynatrace) | measured | 9,983.97 | 0.03 | 224.45 |
| traces | Pass-Through | OpenTelemetry Collector | measured | 9,983.96 | 0.02 | 226.82 |
| traces | Pass-Through | Cribl | semantic_mismatch | — | — | — |
| traces | Pass-Through | Vector (Datadog) | measured | 9,983.96 | 0.30 | 165.23 |
| traces | Pass-Through | Fluent Bit | measured | 9,983.98 | 0.06 | 27.66 |
| traces | Pass-Through | Fluentd | measured | 9,983.97 | 0.12 | 355.11 |
| traces | Filter | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| traces | Filter | Edge Delta (Go) | semantic_mismatch | — | — | — |
| traces | Filter | Bindplane (Dynatrace) | measured | 9,983.98 | 0.02 | 225.71 |
| traces | Filter | OpenTelemetry Collector | measured | 9,983.96 | 0.02 | 228.89 |
| traces | Filter | Cribl | semantic_mismatch | — | — | — |
| traces | Filter | Vector (Datadog) | not_configured | — | — | — |
| traces | Filter | Fluent Bit | not_configured | — | — | — |
| traces | Filter | Fluentd | not_configured | — | — | — |
| traces | Enrich | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| traces | Enrich | Edge Delta (Go) | semantic_mismatch | — | — | — |
| traces | Enrich | Bindplane (Dynatrace) | measured | 9,983.97 | 0.03 | 225.61 |
| traces | Enrich | OpenTelemetry Collector | measured | 9,983.97 | 0.03 | 228.20 |
| traces | Enrich | Cribl | semantic_mismatch | — | — | — |
| traces | Enrich | Vector (Datadog) | not_configured | — | — | — |
| traces | Enrich | Fluent Bit | measured | 9,983.97 | 0.06 | 28.18 |
| traces | Enrich | Fluentd | not_configured | — | — | — |
| traces | Mask | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| traces | Mask | Edge Delta (Go) | semantic_mismatch | — | — | — |
| traces | Mask | Bindplane (Dynatrace) | measured | 9,983.97 | 0.03 | 227.40 |
| traces | Mask | OpenTelemetry Collector | measured | 9,983.97 | 0.03 | 229.38 |
| traces | Mask | Cribl | semantic_mismatch | — | — | — |
| traces | Mask | Vector (Datadog) | not_configured | — | — | — |
| traces | Mask | Fluent Bit | measured | 9,983.97 | 0.06 | 27.88 |
| traces | Mask | Fluentd | not_configured | — | — | — |
| traces | Sample | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| traces | Sample | Edge Delta (Go) | semantic_mismatch | — | — | — |
| traces | Sample | Bindplane (Dynatrace) | measured | 9,983.97 | 0.03 | 226.25 |
| traces | Sample | OpenTelemetry Collector | measured | 9,983.96 | 0.03 | 227.94 |
| traces | Sample | Cribl | semantic_mismatch | — | — | — |
| traces | Sample | Vector (Datadog) | not_configured | — | — | — |
| traces | Sample | Fluent Bit | measured | 9,983.95 | 0.04 | 24.01 |
| traces | Sample | Fluentd | not_configured | — | — | — |
| traces | Tail | Edge Delta (Rust) | semantic_mismatch | — | — | — |
| traces | Tail | Edge Delta (Go) | semantic_mismatch | — | — | — |
| traces | Tail | Bindplane (Dynatrace) | measured | 9,983.97 | 0.06 | 288.33 |
| traces | Tail | OpenTelemetry Collector | measured | 9,983.96 | 0.06 | 288.54 |
| traces | Tail | Cribl | not_configured | — | — | — |
| traces | Tail | Vector (Datadog) | not_configured | — | — | — |
| traces | Tail | Fluent Bit | delivery_mismatch | 9,983.97 | 0.04 | 39.92 |
| traces | Tail | Fluentd | not_configured | — | — | — |
| traces | Metrics | Edge Delta (Rust) | not_configured | — | — | — |
| traces | Metrics | Edge Delta (Go) | not_configured | — | — | — |
| traces | Metrics | Bindplane (Dynatrace) | measured | 9,983.93 | 0.02 | 224.20 |
| traces | Metrics | OpenTelemetry Collector | measured | 9,983.91 | 0.02 | 227.05 |
| traces | Metrics | Cribl | not_configured | — | — | — |
| traces | Metrics | Vector (Datadog) | not_configured | — | — | — |
| traces | Metrics | Fluent Bit | not_configured | — | — | — |
| traces | Metrics | Fluentd | not_configured | — | — | — |

## Correctness and configuration evidence

### Fluentd

Commit: `3d81b4944a7f739f875c8a4fa378e7608b746991`. Binary SHA-256: `640d4d2f13f3154a4bab7da053e9aae782fcdf4aba9daded6246ebb766818ffc`.

- metrics/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/filter: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/enrich: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/aggregate: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/rollup: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/combined: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/filter: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/enrich: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/mask: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/sample: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/tail: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/metrics: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
### Cribl

Commit: `5ca7c8353f6fcccc95480ac3f356ae9822bf1c2c`. Binary SHA-256: `e0c69e0b2bf1c8f5c0d114a925a67830f37c57d9957952bf38eb72be1ffc7882`.

- metrics/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/filter: **semantic_mismatch** — expected 384 output records, got 512; missing=0, unexpected=128
- metrics/enrich: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- metrics/aggregate: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/rollup: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/combined: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/pass-through: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/filter: **semantic_mismatch** — expected 384 output records, got 512; missing=384, unexpected=512
- traces/enrich: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/mask: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/sample: **semantic_mismatch** — sample changed or duplicated a span
- traces/tail: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/metrics: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
### OpenTelemetry Collector

Commit: `c2c4a0c, 034ba8244a2d9ca4ad5601bb1050ce687d3744d1, 268e906b83ffdc8660f2456110b6fc94eac52970`. Binary SHA-256: `2425bdf5f89042cd71f56cf5a66b41681d340cbe14c0b1899bcfe2a3a685a064`.

- metrics/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/filter: **correct** — expected 384 output records, got 384; missing=0, unexpected=0
- metrics/enrich: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/aggregate: **semantic_mismatch** — expected 16 output records, got 24; missing=16, unexpected=24
- metrics/rollup: **semantic_mismatch** — expected 128 output records, got 64; missing=128, unexpected=64
- metrics/combined: **semantic_mismatch** — expected 4 output records, got 2; missing=4, unexpected=2
- traces/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/filter: **correct** — expected 384 output records, got 384; missing=0, unexpected=0
- traces/enrich: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/mask: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/sample: **correct** — trace-ID sample retained 49.2%; expected approximately 50%
- traces/tail: **correct** — expected 128 output records, got 128; missing=0, unexpected=0
- traces/metrics: **correct** — span count=512, generated counter=512, histogram count=512, errors=64/64, latency_sum_valid=True
### Edge Delta (Rust)

Commit: `5238928f7f45d0bb611938f3b9107fe2ece1f83c, 034ba8244a2d9ca4ad5601bb1050ce687d3744d1`. Binary SHA-256: `a6a3cced7c870bddd4308c9a7dea970423afb11ff539d8600afeaf4e748a72ad`.

- metrics/pass-through: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- metrics/filter: **semantic_mismatch** — expected 384 output records, got 384; missing=384, unexpected=384
- metrics/enrich: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- metrics/aggregate: **semantic_mismatch** — expected 16 output records, got 16; missing=16, unexpected=16
- metrics/rollup: **semantic_mismatch** — expected 128 output records, got 128; missing=128, unexpected=128
- metrics/combined: **semantic_mismatch** — expected 4 output records, got 4; missing=4, unexpected=4
- traces/pass-through: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/filter: **semantic_mismatch** — expected 384 output records, got 384; missing=384, unexpected=384
- traces/enrich: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/mask: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/sample: **semantic_mismatch** — trace-ID sample retained 0.0%; expected approximately 50%
- traces/tail: **semantic_mismatch** — expected 128 output records, got 128; missing=128, unexpected=128
- traces/metrics: **not_configured** — Span-to-metrics adapter pending; extract_metric is log-oriented.
### Fluent Bit

Commit: `3d81b4944a7f739f875c8a4fa378e7608b746991`. Binary SHA-256: `b3c8e464343ecbc298919bb68ae1f91d3479575881516e57fd0fb4097a95c1de`.

- metrics/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/filter: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/enrich: **semantic_mismatch** — expected 512 output records, got 64; missing=512, unexpected=64
- metrics/aggregate: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/rollup: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/combined: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/filter: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/enrich: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/mask: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/sample: **correct** — trace-ID sample retained 50.4%; expected approximately 50%
- traces/tail: **correct** — expected 128 output records, got 128; missing=0, unexpected=0
- traces/metrics: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
### Vector (Datadog)

Commit: `797ab58`. Binary SHA-256: `275d0efbd3288fa5028bc9acc477cd38198aea93360c96f0e8989d775b3e179b`.

- metrics/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/filter: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/enrich: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/aggregate: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/rollup: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- metrics/combined: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/filter: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/enrich: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/mask: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/sample: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/tail: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
- traces/metrics: **not_configured** — Native scenario adapter pending; this is not an unsupported-vendor claim.
### Edge Delta (Go)

Commit: `5238928f7f45d0bb611938f3b9107fe2ece1f83c, 034ba8244a2d9ca4ad5601bb1050ce687d3744d1`. Binary SHA-256: `a22b72d54ca94e083adbe95810737dd7b8f77c4a77d3ba6c77df27c0fd1b9896`.

- metrics/pass-through: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- metrics/filter: **semantic_mismatch** — expected 384 output records, got 384; missing=384, unexpected=384
- metrics/enrich: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- metrics/aggregate: **semantic_mismatch** — expected 16 output records, got 512; missing=16, unexpected=512
- metrics/rollup: **semantic_mismatch** — expected 128 output records, got 512; missing=128, unexpected=512
- metrics/combined: **semantic_mismatch** — expected 4 output records, got 512; missing=4, unexpected=512
- traces/pass-through: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/filter: **semantic_mismatch** — expected 384 output records, got 384; missing=384, unexpected=384
- traces/enrich: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/mask: **semantic_mismatch** — expected 512 output records, got 512; missing=512, unexpected=512
- traces/sample: **semantic_mismatch** — sample changed span fields: resource,kind,time,end; retained 264 spans
- traces/tail: **semantic_mismatch** — expected 128 output records, got 128; missing=128, unexpected=128
- traces/metrics: **not_configured** — Span-to-metrics adapter pending; extract_metric is log-oriented.
### Bindplane (Dynatrace)

Commit: `3d81b4944a7f739f875c8a4fa378e7608b746991, 034ba8244a2d9ca4ad5601bb1050ce687d3744d1, 268e906b83ffdc8660f2456110b6fc94eac52970`. Binary SHA-256: `68b5987d05cad907da50bab64c47f9bbf97d0ba3938cf7fddf4dbeb3ca58e33b`.

- metrics/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/filter: **correct** — expected 384 output records, got 384; missing=0, unexpected=0
- metrics/enrich: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- metrics/aggregate: **semantic_mismatch** — expected 16 output records, got 24; missing=16, unexpected=24
- metrics/rollup: **semantic_mismatch** — expected 128 output records, got 64; missing=128, unexpected=64
- metrics/combined: **semantic_mismatch** — expected 4 output records, got 2; missing=4, unexpected=2
- traces/pass-through: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/filter: **correct** — expected 384 output records, got 384; missing=0, unexpected=0
- traces/enrich: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/mask: **correct** — expected 512 output records, got 512; missing=0, unexpected=0
- traces/sample: **correct** — trace-ID sample retained 49.2%; expected approximately 50%
- traces/tail: **correct** — expected 128 output records, got 128; missing=0, unexpected=0
- traces/metrics: **correct** — span count=512, generated counter=512, histogram count=512, errors=64/64, latency_sum_valid=True

Missing adapters (`not_configured`) are harness work remaining, not proof that a vendor cannot support the scenario. Raw configurations, correctness captures, calibration and measurements are in the accompanying evidence archive. Each result records its benchmark commit and binary hash. No release or public website is updated by this workflow.
