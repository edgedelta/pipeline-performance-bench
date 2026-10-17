# Further metric optimization

[Interactive comparison](index.html) · [Raw results](results.json) · [Rust PR #21](https://github.com/edgedelta/red/pull/21)

The CPU profile identified allocation/freeing and metric-map construction as hot paths. `6609c21` avoids constructing the full metric context when aggregation expressions only read metric attributes/resources. Expressions needing the full context retain the existing path. Distinct-count expressions are also compiled once. The saved `5440855` baseline remains available separately.

All runs use 10,000 requests/sec × 512 points, separate c8i.8xlarge load/agent/sink hosts, the Rust generator, OTLP/gRPC input and uncompressed OTLP/HTTP output. Baseline and candidate use the same hosts and configurations. CPU cost is total CPU through delivery divided by the measured input window. All scored rows sustained the target and passed operation and delivery checks with zero RPC errors.

## Matched 30-second comparison

| Scenario | Saved Rust | Candidate Rust | OTel 0.162.0 | Rust CPU reduction vs saved |
|---|---:|---:|---:|---:|
| pass-through | 5.034 | 5.012 | 5.785 | 0.4% |
| filter | 5.279 | 5.305 | 6.249 | -0.5% |
| aggregate | 12.233 | 4.570 | 18.102 | 62.6% |

Pass-Through and Filter are effectively unchanged; their small differences are not claimed as improvements. Aggregate has a substantial reduction versus the same Rust implementation's baseline.

## Longer aggregation confirmation

Two 60-second trials per agent, with OTel first (reversed vendor order). Median CPU cost: Rust **4.656**, OTel **17.084**. Individual trials are retained in `validation/aggregate/results.json`.

**Aggregate is a native-behavior comparison, not equal output work.** Rust sums over 10-second event-time windows; OTel reduces labels within each batch. Both preserve sums and remove host cardinality, but Rust emits fewer points. The before/after Rust comparison uses identical windowing and output semantics.

## Microbenchmark and profiles

The release-mode microbenchmark (`e841d0c`, test-only change after measured agent revision `6609c21`) compares full and field-only aggregation contexts in the same executable, alternating order across eight rounds. Every pair checks identical serialized aggregate output. Fixture construction and flush serialization are outside the measured loop. The test uses the system allocator; the agent uses mimalloc, so these isolated timings are a screening result, not an end-to-end prediction.

`median full=1398.92 field=392.87 ns/point reduction=71.9%`

See [microbenchmark output](microbenchmark.txt), [method and commands](microbenchmark-method.txt), [pass-through CPU profile](profile-pass-through.txt), and [aggregation CPU profile](profile-aggregate.txt). Profiles were captured in separate diagnostic runs and excluded from scored trials. Baseline pass-through samples included 16.06% in `mi_free` and 10.10% in `mi_malloc_aligned`; aggregation included 9.59%/12.36% respectively, plus 5.40% in map cloning. These are sampled self-time percentages, not precise allocation counts.

The first microbenchmark attempt detected a warm-up fixture mismatch between modes; the corrected benchmark resets the resource group before each mode. Only corrected successful timings are reported.

## Configurations and validation

- pass-through: [Rust](candidate-1/pass-through/red-512-10000-0.yaml), [OTel](candidate-1/pass-through/otelcol-512-10000-0.yaml).
- filter: [Rust](candidate-1/filter/red-512-10000-0.yaml), [OTel](candidate-1/filter/otelcol-512-10000-0.yaml).
- aggregate: [Rust](candidate-1/aggregate/red-512-10000-0.yaml), [OTel](candidate-1/aggregate/otelcol-512-10000-0.yaml).

Input uses 64 connections and 1,024 in-flight requests with 64 recurring resource groups and 64 host series. There is no added batch processor or OTel sending queue; output batching matches in Pass-Through and Filter. Rust retains built-in retry handling, OTel retries are disabled, and successful measurements report no RPC errors. Stateful scenarios start fresh and drain through final delivery.

The aggregation optimization passed 1,252 library tests (one ignored), including full-context equivalence across aggregation functions and passthrough behavior. The corrected microbenchmark passed separately. The harness passed 11 tests with one skipped. Raw configs, fixture protobufs, warm-up evidence and source/binary provenance accompany the report. All changes remain in draft PRs; the public Pages URL is unchanged.
