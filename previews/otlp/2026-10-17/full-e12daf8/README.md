# Metric scenarios — partial full run

[Visual report](index.html) · [Raw trials](results.json) · [Rust PR #21](https://github.com/edgedelta/red/pull/21)

**The full suite is not complete.** The local Mac repeatedly entered maintenance sleep, interrupting SSH control sessions. A temporary idle-sleep assertion did not prevent those maintenance-sleep cycles. Attempts to rerun the remaining cases were also interrupted during setup. All provisioned resources were subsequently destroyed. No missing case is represented as a valid agent measurement.

10,000 requests/sec × 512 points; two 60-second trials per vendor/scenario were intended, using isolated c8i.8xlarge load, agent and sink hosts. Rust generator/sink, OTLP/gRPC input, uncompressed OTLP/HTTP output, 64 connections and up to 1,024 in-flight requests. The same e12daf8 Rust binary was used throughout. No agent or harness code was changed for this run.

CPU cost includes final delivery, divided by the input-window duration. Lower is better. Values below require two valid trials at the offered load.

| Scenario | Rust | OTel | Bindplane |
|---|---:|---:|---:|
| pass-through | 4.709 | 5.926 | 5.806 |
| filter | 4.932 | 6.637 | 6.633 |
| enrich | 6.114 | 7.796 | 8.264 |
| aggregate | 4.709 | 16.884 | 17.278 |
| rollup | 5.328 | Incomplete | Incomplete |
| combined | Incomplete | Incomplete | Incomplete |

The first four scenarios completed all 24 trials at the target with verified operations/delivery and zero RPC errors. Rust Rollup completed both trials at the target. OTel Rollup trial 0 reached 3,464 requests/sec; Bindplane trial 0 reached 3,078. Both preserved accepted values, but their second trials were interrupted. Combined has no valid result. The unsuccessful OTel retry and original interrupted attempts are retained alongside the scored data. The visual report marks incomplete trial pairs N/A, and lists individual successful shortfall measurements in the table.

Aggregate uses native implementations: Rust reduces over 10-second windows; collectors reduce labels within each input batch. Output volume differs, so this is not equal-output-work aggregation. Rollup retains host labels with a 60-second interval. Combined combines cardinality reduction and interval rollup. Pass-Through/Filter/Enrich have matching output batch sizes and operation checks. The fixture has one metric per 512-point request; mixed metadata has correctness tests but no separate throughput measurements here.

The previous candidate library suite passed 1,254 tests (two ignored). The PR remains draft/unmerged; the public site is unchanged. SSH credentials remained local.

## Configurations

- pass-through: [red](pass-through/red-512-10000-0.yaml), [otelcol](pass-through/otelcol-512-10000-0.yaml), [bindplane](pass-through/bindplane-512-10000-0.yaml).
- filter: [red](filter/red-512-10000-0.yaml), [otelcol](filter/otelcol-512-10000-0.yaml), [bindplane](filter/bindplane-512-10000-0.yaml).
- enrich: [red](enrich/red-512-10000-0.yaml), [otelcol](enrich/otelcol-512-10000-0.yaml), [bindplane](enrich/bindplane-512-10000-0.yaml).
- aggregate: [red](aggregate/red-512-10000-0.yaml), [otelcol](aggregate/otelcol-512-10000-0.yaml), [bindplane](aggregate/bindplane-512-10000-0.yaml).
- rollup: [red](rollup/red-512-10000-0.yaml), [otelcol](rollup/otelcol-512-10000-0.yaml), [bindplane](rollup/bindplane-512-10000-0.yaml).
- combined: [red](combined/red-512-10000-0.yaml), [otelcol](combined/otelcol-512-10000-0.yaml).
