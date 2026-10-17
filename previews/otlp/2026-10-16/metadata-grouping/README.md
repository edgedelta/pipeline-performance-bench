# Metadata and output grouping experiments

[Visual report](index.html) · [Results](results.json)

An OTLP request can contain multiple resources and metrics with different names, units, types, temporality, and monotonicity. Within a metric, point attributes and timestamps can differ independently. Sharing must preserve these boundaries; it cannot assume that the whole request has one metadata set.

## Results

Eight alternating-order rounds, each processing 1,000 batches of 512 points on an isolated c8i.8xlarge host. Values are median nanoseconds per point from an optimized library test executable. The system allocator is used in these tests; the production agent uses mimalloc. These are isolated costs, not full-agent speedups.

| Metadata groups per 512 points | Owned strings | Shared metadata | Time reduction |
|---|---:|---:|---:|
| 1 | 92.24 | 12.82 | 86.1% |
| 8 | 92.30 | 10.72 | 88.4% |
| 64 | 92.64 | 21.86 | 76.4% |
| 512 | 90.67 | 137.75 | -51.9% |

The metadata experiment is a representation prototype, not a production MetricItem refactor. It measures cloning/dropping the name, unit, empty description, and statistic-type strings versus constructing shared metadata once per group and cloning Arc references. Shared-object construction and cleanup are included. Copy-on-write isolation is checked. Sharing is promising for repeated metadata, but a strategy for singleton groups and full-agent validation are needed before adoption.

| Encoder workload | Existing | Candidate | Time reduction |
|---|---:|---:|---:|
| One metadata group | 244.04 | 234.25 | 4.0% |
| 8 metadata groups | 252.40 | 252.15 | 0.1% |
| 64 metadata groups | 297.39 | 297.59 | -0.1% |
| 512 metadata groups | 617.65 | 638.93 | -3.4% |
| Last point differs | 245.17 | 424.84 | -73.3% |

The encoder experiment uses the actual production encoding function with a candidate grouping shortcut. The full metadata key and resource identity are checked before choosing the homogeneous path; mixed batches use general grouping. The shortcut was rejected and reverted: its small homogeneous gain did not justify the large late-mismatch regression. No production encoder or metadata changes were retained.

Correctness tests compare both encoders and the generated protobuf implementation. Coverage includes 1/8/64/512 interleaved groups; identical resources held in distinct allocations; and a final point differing in name, unit, description, type, temporality, monotonicity, or resource. Point attributes differ within each batch. Three correctness tests and both ignored microbenchmarks passed.

## Reproduce

Start from the base commit in [source.json](source.json), then apply [experiment.patch](experiment.patch) in the Rust repository. On Linux:

```sh
cargo test --release --locked --lib output::otlp::metric_wire::tests -- --nocapture --test-threads=1
cargo test --release --locked --lib benchmark_metadata_sharing -- --ignored --nocapture --test-threads=1
cargo test --release --locked --lib benchmark_output_grouping -- --ignored --nocapture --test-threads=1
```

The measured executable was cross-compiled with Zig using the release profile. CPU details and raw outputs are included. The isolated host and its infrastructure were destroyed afterward. The existing successful agent optimization and public benchmark site are unchanged.
