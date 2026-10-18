# Trace request-rate ladder

[Interactive chart](index.html) · [Raw results](results.json) · [Metrics ladder](../metrics-ladder/index.html)

Pass-Through, Filter, Mask, Sample and Tail at **1k / 2k / 4k / 8k requests/sec**, with **512 spans/request**. One 60-second trial per case; 60 cases attempted. Rust 8c29318, OTel Collector 0.162.0 and Bindplane 1.110.1 run sequentially on the same isolated c8i.8xlarge agent host. Rust load generator and sink have separate c8i.8xlarge hosts. OTLP/gRPC input and uncompressed OTLP/HTTP output; 64 connections, 1,024 in-flight requests and 30-second request timeout. Exact source and binary provenance is in source.json and raw results.

Status counts: {'measured': 47, 'input_shortfall': 9, 'operation_mismatch': 4}. 56/60 cases passed their scenario checks. 20/20 direct-to-sink calibrations passed. Sampling checks are statistical, as described below.

## Highest tested passing tier

A passing case sustains at least 95% of offered load with no RPC errors/rejections and passes its scenario checks. These are tested tiers, not maximum capacity estimates. A dash means no tier passed all checks.

| Scenario | Rust req/s | OTel req/s | Bindplane req/s |
|---|---:|---:|---:|
| pass-through | 8,000 | 8,000 | 8,000 |
| filter | 8,000 | 8,000 | 8,000 |
| mask | 4,000 | 8,000 | 8,000 |
| sample | 8,000 | 8,000 | 8,000 |
| tail | — | — | — |

## Verified CPU measurements

Total CPU seconds through final delivery divided by the configured 60-second offered-load window. Unlike wall-clock normalization, this includes the cost of requests completing after the load window without inflating efficiency. † denotes an input shortfall; lower CPU does not imply handling the full target. A dash means no verified measurement. Memory in the chart is final RSS, not peak memory.

| Scenario | Offered req/s | Rust cores | OTel cores | Bindplane cores |
|---|---:|---:|---:|---:|
| pass-through | 1,000 | 0.785 | 1.028 | 1.028 |
| pass-through | 2,000 | 1.848 | 1.981 | 2.036 |
| pass-through | 4,000 | 3.781 | 3.897 | 4.047 |
| pass-through | 8,000 | 8.184 | 8.232 | 8.388 |
| filter | 1,000 | 0.756 | 1.045 | 1.062 |
| filter | 2,000 | 1.792 | 2.052 | 2.101 |
| filter | 4,000 | 3.690 | 4.122 | 4.150 |
| filter | 8,000 | 7.914 | 8.768 | 8.668 |
| mask | 1,000 | 4.779 | 1.054 | 1.074 |
| mask | 2,000 | 9.798 | 2.080 | 2.141 |
| mask | 4,000 | 26.260 | 4.259 | 4.277 |
| mask | 8,000 | 32.080 † | 8.469 | 8.936 |
| sample | 1,000 | 0.812 | 1.447 | 1.465 |
| sample | 2,000 | 1.810 | 2.904 | 2.994 |
| sample | 4,000 | 3.721 | 5.997 | 6.094 |
| sample | 8,000 | 7.832 | 13.047 | 12.511 |
| tail | 1,000 | — | 4.107 † | 4.073 † |
| tail | 2,000 | — | 3.760 † | 3.943 † |
| tail | 4,000 | — | 3.949 † | 3.994 † |
| tail | 8,000 | — | 3.977 † | 4.005 † |

## Tail delivery audit

Rust Tail cases with failed exact-count verification are excluded from efficiency scores. The deficit is retained spans expected from acknowledged input minus spans received after the final drain.

| Offered req/s | Expected retained spans | Delivered spans | Missing spans |
|---|---:|---:|---:|
| 1,000 | 3,160,448 | 3,160,352 | 96 |
| 2,000 | 3,180,544 | 3,180,442 | 102 |
| 4,000 | 3,240,704 | 3,240,604 | 100 |
| 8,000 | 3,153,536 | 3,153,452 | 84 |

Raw traffic counters retain the generic field name `points`; for the traces signal these count spans.

## Method and limitations

Each request contains 256 complete two-span traces, with unique IDs across requests, stable resource metadata, a 20ms duration, one event and one link per span. Parent and child arrive in the same request; this does not test delayed or distributed span arrival.

Filter drops health traces (25%). Mask replaces the secret attribute with REDACTED. Sample uses each vendor’s native 50% trace-ID sampler. Tail keeps error traces (25%) after a 1-second decision window. Tail buffers allow four million traces in each agent. Collectors batch Tail exports on a 500ms timer, matching Rust’s decision-check cadence; actual batch sizes remain native. A one-million-span collector cap and 256MiB sink request limit bound exports. Pass-Through/Mask preserve 512-span batches and Filter preserves 384-span batches, verified at the sink. Sample batch sizes follow native selections.

The sink verifies payload fields, parent/child counts and matching trace-ID fingerprints. Pass-Through, Filter, Mask and Tail also require exact retained-span counts. Sample checks 45–55% retention and intact paired spans; it does not independently verify the vendor-specific retained set or rule out small delivery loss. `sampling_verified` is separate from `delivery_verified`. Invalid delivery is not scored as an efficiency result.

Tail starts with a fresh agent without warm-up. Other scenarios receive a five-second warm-up, whose results are excluded. All offered tiers are attempted independently. Small differences require repeat trials. This fixture does not measure arbitrary span sizes, mixed resource metadata, or maximum capacity.

The prior metric report remains unchanged. Both PRs remain draft/unmerged and the public Pages site is unchanged.

The 8k Sample Rust and OTel cases have extended collection intervals (about 382s and 124s). Their offered-load windows remain 60s, and all requests completed without RPC errors. The report uses CPU seconds / 60, including any CPU consumed during the extended collection interval; the raw `cpu_cores` wall-clock average must not be used for comparisons.

![8k trace tier](preview.png)

All seven temporary benchmark resources were destroyed; Terraform state is empty.
