# Full metric scenarios — Rust e12daf8

[Visual report](index.html) · [Raw results](results.json) · [Rust draft PR #21](https://github.com/edgedelta/red/pull/21)

Latest metadata-sharing candidate, tested at 10,000 requests/sec × 512 points/request (5.12 million points/sec). Two 60-second trials per agent/scenario; three isolated c8i.8xlarge hosts for Rust generator, agent and Rust sink. All six load calibrations passed. OTLP/gRPC input and uncompressed OTLP/HTTP output, 64 input connections, up to 1,024 in-flight requests, 64 recurring resource groups × 64 host series. Source commit: `e12daf870e445062ea1e5d08eb19089070b7ab05`; binary SHA-256: `6553707336f9f45daca4d3f64dbe0261f17192517d577805a34e28a622c26841`.

Median CPU cost through final delivery, normalized to input-window duration; lower is better. † means at least one trial did not sustain the offered load. N/A means delivery or operation verification failed; it is not a vendor capability claim.

| Scenario | Edge Delta Rust | OTel | Bindplane |
|---|---:|---:|---:|
| pass-through | 4.709 | 5.926 | 5.806 |
| filter | 4.932 | 6.637 | 6.633 |
| enrich | 6.114 | 7.796 | 8.264 |
| aggregate | 4.709 | 16.884 | 17.278 |
| rollup | 5.208 | 2.314 † | 1.683 † |
| combined | 4.495 | 6.359 † | 8.089 † |

Trial statuses: input_shortfall: 8, measured: 28.

Latest Rust candidate e12daf8, two 60-second trials per vendor and scenario. Rollup and Combined were rerun together on fresh hosts after a local network outage; the other four scenarios share the original hosts. Pass-Through, Filter and Enrich use matched output batch sizes. Aggregate uses native behavior: Rust reduces over 10-second windows; OTel/Bindplane reduce labels within each batch. Rollup and Combined use 60-second intervals; output timing and volume can differ. CPU includes final delivery. This fixture has one metric with 512 points per request; mixed-metadata throughput is not measured.

Combined means cardinality reduction plus interval rollup in this suite. It does not combine all six operations. Reducing scenarios check preserved sums, reduced point count and expected host-label handling; they do not enforce equal output volume or identical window boundaries. For the other scenarios, verification includes output batch shape and expected filter/enrichment behavior. Every trial, achieved rate, delivery count and status is visible in the report. A local network outage interrupted the initial Rollup repeats and Combined measurements. All Rollup and Combined cases were rerun together on fresh hosts of the same type with unchanged configurations and binaries. The original attempts, including successful Rust Rollup and collector shortfalls, are retained under interrupted-attempts/. The final report uses the complete recovery run for those two scenarios; none of the first four scenarios was replaced.

The candidate's full library suite passed 1,254 tests (two ignored), including mixed metadata, singleton ownership, copy-on-write isolation, and serialization compatibility. This run changes no agent code. The rejected output-grouping shortcut remains excluded. Neither PR is merged; the public Pages site is unchanged.

## Exact configurations

- pass-through: [Rust](pass-through/red-512-10000-0.yaml), [OTel](pass-through/otelcol-512-10000-0.yaml), [Bindplane](pass-through/bindplane-512-10000-0.yaml).
- filter: [Rust](filter/red-512-10000-0.yaml), [OTel](filter/otelcol-512-10000-0.yaml), [Bindplane](filter/bindplane-512-10000-0.yaml).
- enrich: [Rust](enrich/red-512-10000-0.yaml), [OTel](enrich/otelcol-512-10000-0.yaml), [Bindplane](enrich/bindplane-512-10000-0.yaml).
- aggregate: [Rust](aggregate/red-512-10000-0.yaml), [OTel](aggregate/otelcol-512-10000-0.yaml), [Bindplane](aggregate/bindplane-512-10000-0.yaml).
- rollup: [Rust](rollup/red-512-10000-0.yaml), [OTel](rollup/otelcol-512-10000-0.yaml), [Bindplane](rollup/bindplane-512-10000-0.yaml).
- combined: [Rust](combined/red-512-10000-0.yaml), [OTel](combined/otelcol-512-10000-0.yaml), [Bindplane](combined/bindplane-512-10000-0.yaml).

## Achieved request rates in the added scenarios

| Scenario | Rust req/s | OTel req/s | Bindplane req/s |
|---|---:|---:|---:|
| Rollup | 9,999.77 | 3,426.76 | 2,365.72 |
| Combined | 9,999.75 | 3,464.00 | 3,742.47 |

All 12 added trials passed operation and delivery checks with zero RPC errors or rejected points. Rust sustained the target in all four trials; the eight collector trials fell short. Low CPU in a shortfall trial does not mean the agent processed the full offered load. All seven cloud resources were destroyed after completion; Terraform state is empty.
