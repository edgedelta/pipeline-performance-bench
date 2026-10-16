> Superseded by the [matched-output comparison](../matched-output/README.md). This historical run used different output batching across agents.

# Rust request-rate benchmark preview

[Download the interactive report](index.html) and open it locally. This report is separate from the public Pages site and the previous item-rate report.

Metrics Pass-Through, Rust generator and sink, three separate c8i.8xlarge hosts, 64 persistent gRPC connections, 1,024 maximum in-flight requests, 30-second agent trials. Tests use the same released agent binaries as the previous preview. The generator and sink receive no agent CPU allocation.

| Offered requests/sec | Points/request | Offered points/sec | Harness reached requests/sec | Calibration |
|---:|---:|---:|---:|---|
| 10,000 | 1 | 10,000 | 9,999 | Passed |
| 100,000 | 1 | 100,000 | 99,994 | Passed |
| 10,000 | 512 | 5,120,000 | 9,999 | Passed |
| 100,000 | 512 | 51,200,000 | 60,487 | Harness-limited; vendors unmeasured |

OTel and Bindplane sustained the one-point 10k and 100k request-rate trials with verified delivery. RED fell short of these offered rates under the tested connection/concurrency settings and reported RPC errors. All agents fell short of 10k requests/sec with 512-point batches. These are observed results for the recorded configurations, not vendor maximum-capacity claims. The configurations retain the earlier OTLP/HTTP export behavior, including disabled collector sending queues; export backpressure and client concurrency can limit throughput before CPU saturation.

The chart displays actual requests/sec, points/sec, and CPU cores. Dashed bars identify input or delivery shortfalls. CPU includes the final delivery drain; input-window CPU is also retained in JSON. Timing includes SSH control overhead. Direct gRPC calibration verifies the ingress workload, not every agent's HTTP export shape; sink CPU and output counts/bytes are retained for diagnosis. Repeat trials before interpreting small differences.

`results.json` contains calibration, delivery totals and sums, request errors, missed requests, latency buckets, CPU measurements, binary hashes, versions, and host information. YAML files contain the tested configurations. Binary `.pb` files contain the fixtures. `measured-harness-source.tgz` is the exact Rust source and dependency lock used for this run; the maintained harness additionally records representative RPC error messages and has more integration coverage.

[Harness usage and methodology](../../../../otlpbench/RPS.md). The PR remains unmerged. Temporary test infrastructure is destroyed after collection.
