# Pass-Through with matched output batches

[Download the interactive report](index.html). This supersedes the earlier request-rate comparison, whose output batching differed between agents.

All agents receive OTLP/gRPC and export uncompressed OTLP/HTTP protobuf. The collectors have no batch processor; output request sizes must equal input request sizes. The sink checks the full size distribution during warm-up and measurement. Collector HTTP pools are sized for 1,024 concurrent requests to prevent connection churn and port exhaustion. Agents retain their native export concurrency; this is not a claim of identical internal execution.

Three isolated c8i.8xlarge hosts, 64 persistent gRPC connections, 1,024 maximum in-flight requests, 30 seconds per measured trial, and a five-second readiness warm-up at 1,000 requests/sec. CPU includes the final delivery drain and SSH control overhead. These are fixed-load measurements, not maximum-capacity claims.

| Vendor | Input/output points per request | Offered requests/sec | Reached requests/sec | CPU cores | Output batch verified | Status |
|---|---:|---:|---:|---:|---|---|
| Edge Delta (Rust) | 1 | 10,000 | 3,875 | 0.292 | Yes, every request | input_shortfall |
| OTel Collector | 1 | 10,000 | 10,000 | 1.727 | Yes, every request | measured |
| Bindplane | 1 | 10,000 | 10,000 | 1.761 | Yes, every request | measured |
| Edge Delta (Rust) | 1 | 100,000 | 2,925 | 0.226 | Yes, every request | input_shortfall |
| OTel Collector | 1 | 100,000 | 99,861 | 15.323 | Yes, every request | measured |
| Bindplane | 1 | 100,000 | 99,814 | 15.622 | Yes, every request | measured |
| Edge Delta (Rust) | 512 | 10,000 | 640 | 0.751 | Yes, every request | input_shortfall |
| OTel Collector | 512 | 10,000 | 10,000 | 5.116 | Yes, every request | measured |
| Bindplane | 512 | 10,000 | 9,999 | 5.172 | Yes, every request | measured |
| Edge Delta (Rust) | 512 | 100,000 | — | — | Unmeasured | harness_limited |
| OTel Collector | 512 | 100,000 | — | — | Unmeasured | harness_limited |
| Bindplane | 512 | 100,000 | — | — | Unmeasured | harness_limited |

All measured output requests passed the batch-size check, and accepted point counts and sums were delivered. RED still fell short of the offered rates and reported gRPC cancellations; matching output batching does not remove those observed shortfalls. The tested RED release sends OTLP output requests serially, while collector exporter execution differs. That is a further performance investigation, not a correction applied to these measurements.

`results.json` retains calibrations, versions, binary hashes, CPU, latency buckets, RPC errors, output counts/bytes, and the exact output request-size histograms. YAML files are the tested configurations. `evidence.tar.gz` additionally retains warm-up records and bounded agent logs. The measured Rust source and dependency lock are archived separately.

[Harness methodology and commands](../../../../otlpbench/RPS.md). This report was generated before merge. The public Pages URL is unchanged; temporary test hosts are destroyed after collection.
