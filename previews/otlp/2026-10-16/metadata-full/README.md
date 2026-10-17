# Shared metric metadata: full agent comparison

[Visual report](index.html) · [Raw results](results.json) · [Rust PR #21](https://github.com/edgedelta/red/pull/21)

This compares the saved `6609c21` agent with metadata-sharing candidate `e12daf8`. The previously rejected output-grouping shortcut remains reverted. The candidate shares scalar metric name, unit, description and statistic-type strings within each OTLP metric; singleton metrics keep inline ownership. Metadata mutation uses copy-on-write so changing one point cannot mutate another point's metadata. Point attributes, timestamps, values and resource handling retain their previous behavior. Histogram/summary materialization and other input paths retain owned metadata.

## Full workload

10,000 requests/sec × 512 points/request, isolated c8i.8xlarge load, agent and sink hosts, Rust generator/sink. OTLP/gRPC input and uncompressed OTLP/HTTP output; output batches match between vendors. Each phase runs two 60-second trials per agent and scenario. Both phases use the same hosts and exact configs, with vendor order reversed for the candidate. All 16 scored rows sustained the target and passed operation, delivery and output-batch checks with zero RPC errors.

Median CPU cost is CPU through delivery divided by the input-window duration; lower is better.

| Scenario | Saved Rust | Candidate Rust | OTel in candidate phase | Rust CPU reduction vs saved |
|---|---:|---:|---:|---:|
| pass-through | 5.155 | 4.756 | 5.920 | 7.7% |
| filter | 5.395 | 4.984 | 6.633 | 7.6% |

Individual trials and OTel controls from both phases are retained in the visual report and raw results. These runs use the existing one-metric/512-point fixture. Mixed-metadata correctness was tested separately; this does not establish mixed-metadata or singleton throughput performance.

## Safety and compatibility checks

The full library suite passed: 1,254 tests, two ignored. New coverage includes mixed resources/metric names, units, delta/cumulative sums, independent point attributes and timestamps, singleton ownership, shared ownership within each metric, copy-on-write isolation, and JSON/MessagePack compatibility. Existing input, processor, output and protobuf-equivalence tests also passed. The Rust source remains a draft PR; nothing is merged and the public Pages site is unchanged.

## Configurations

- pass-through: [Rust](candidate/pass-through/red-512-10000-0.yaml), [OTel](candidate/pass-through/otelcol-512-10000-0.yaml).
- filter: [Rust](candidate/filter/red-512-10000-0.yaml), [OTel](candidate/filter/otelcol-512-10000-0.yaml).

The harness uses 64 connections, up to 1,024 in-flight requests and 64 recurring resource groups with 64 host series. There is no additional batch processor or OTel sending queue. Rust retains its delivery retry handling; OTel retries are disabled. Every successful scored run reports zero RPC errors. Warm-up, calibration, final delivery, source commits, binary SHA-256 values and the measured harness archive are included for review.
