# Trace Mask and Tail optimization

Latest 8k offered-load retest (`b200868`): Mask sustains 7,999.6 requests/sec at 9.029 normalized CPU cores, near the OTel/Bindplane reference costs of 8.752/8.978 cores. Tail reaches 1,835.25 requests/sec at 3.774 cores, versus OTel 707.70 at 3.955 cores and Bindplane 717.92 at 4.136 cores. Tail delivers all 14,225,792 expected retained spans and passes payload/pair checks. It remains an input shortfall at the 8k tier, not an 8k pass. Earlier Tail losses remain visible below. The latest commit was retested at 8k; 1k rows belong to earlier recorded commits.

Candidate `5f7da6c` edits eligible trace attributes/resources through the native mutable view. Tail ingestion holds the state lock for a complete input batch, reads status directly from native spans, and evaluates policies outside the shared lock. Generation checks prevent stale decisions from altering evicted and recreated traces. Follow-up `326caf6` replaces per-access ordering-tree updates with a constant-time LRU and emits completed decisions in chunks of at most 4,096 pending trace groups. Both early candidates failed exact Tail delivery at 8k; those results are preserved below. Candidate `b200868` makes incoming batches also drain overdue decisions, so decision progress does not depend solely on scheduling the timer during sustained synchronous input contention.

One 60-second trial per case, 512 spans/request, 64 connections, 1,024 maximum outstanding requests; separate c8i.8xlarge load/agent/sink hosts. All agents use OTLP/gRPC input and uncompressed OTLP/HTTP output. Baseline and candidate ran on the same hosts. These are single trials, not statistical confidence intervals. The final binary was compiled natively on Linux after local fat-LTO compilation exhausted laptop memory; earlier Rust binaries were cross-compiled using Zig. Rust 1.98.0 and the release optimization profile are unchanged; native C dependencies/linking may differ, so small CPU differences should not be attributed solely to source edits. The final chart reuses the OTel/Bindplane reference trials from the preceding iteration on these same hosts.

| Version | Scenario | Offered req/s | Reached req/s | CPU cores through delivery | Status |
|---|---|---:|---:|---:|---|
| Saved Rust | Mask | 1000 | 999.88 | 4.760 | measured |
| Saved Rust | Mask | 8000 | 3775.88 | 32.068 | input_shortfall |
| Saved Rust | Tail | 1000 | 395.10 | 1.652 | operation_mismatch |
| Saved Rust | Tail | 8000 | 400.43 | 1.680 | operation_mismatch |
| Native fields | Mask | 1000 | 999.95 | 0.846 | measured |
| otelcol | Mask | 1000 | 999.97 | 1.082 | measured |
| bindplane | Mask | 1000 | 999.98 | 1.105 | measured |
| Native fields | Mask | 8000 | 7999.53 | 8.793 | measured |
| otelcol | Mask | 8000 | 7999.52 | 8.752 | measured |
| bindplane | Mask | 8000 | 7999.60 | 8.978 | measured |
| Native fields | Tail | 1000 | 999.95 | 2.179 | measured |
| otelcol | Tail | 1000 | 745.88 | 4.269 | input_shortfall |
| bindplane | Tail | 1000 | 741.08 | 4.217 | input_shortfall |
| Native fields | Tail | 8000 | 1301.35 | 1.978 | operation_mismatch |
| otelcol | Tail | 8000 | 707.70 | 3.955 | input_shortfall |
| bindplane | Tail | 8000 | 717.92 | 4.136 | input_shortfall |
| Bounded Tail flush | Mask | 1000 | 999.95 | 0.870 | measured |
| Bounded Tail flush | Mask | 8000 | 7999.63 | 8.959 | measured |
| Bounded Tail flush | Tail | 1000 | 999.97 | 1.610 | measured |
| Bounded Tail flush | Tail | 8000 | 1761.95 | 2.292 | operation_mismatch |
| Cooperative Tail | Mask | 8000 | 7999.60 | 9.029 | measured |
| Cooperative Tail | Tail | 8000 | 1835.25 | 3.774 | input_shortfall |

CPU includes processing through final delivery, divided by the configured 60-second load window. Invalid delivery results are excluded from chart comparisons. Mask checks exact delivery and 512-span output batches. Tail checks retained-span counts, payload and parent/child fingerprints. The fixture has 256 complete two-span traces per request; only the child has ERROR status in retained traces. Mixed metadata is covered by correctness tests.

Validation: the final follow-up passes 1,271 library tests with ten ignored; the initial candidate passed 1,269 with nine ignored; 16 targeted integration tests passed for the first candidate and seven native-processor integration tests passed again for the follow-up; all-target Clippy passed with existing warnings. An initial parallel run had one shared telemetry counter test failure (expected one entry, got zero); both logs are retained. The new concurrent Tail regression failed before the fix (24,354 of 25,600 spans delivered) and passes after it.

Profiles were collected separately from scored trials. Three runs of alternating old/new microbenchmarks measured roughly 5.9 microseconds versus 0.59 microseconds per Mask span, and 2 microseconds versus 23 nanoseconds per Tail status-policy decision. These isolate the edit/policy cost, not full pipeline throughput. The cache microbenchmark measures roughly 400 ns per insert/promote with the ordering tree versus 150 ns with the new LRU (about 2.6x faster). Microbenchmarks use the system allocator; production agents use mimalloc. Raw configs, measurements, profiles, test logs and source hashes are included.

Draft PRs remain unmerged. Public Pages is unchanged. Open index.html for the interactive report.
