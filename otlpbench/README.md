# Metrics and traces benchmarks

Runs on the PR branch without updating the public log benchmark. Input is batched OTLP/gRPC; results have a standalone interactive chart using the public site's colors and controls.

| Signal | Scenarios |
|---|---|
| Metrics | Pass-Through, Filter, Enrich, Aggregate, Rollup, Combined |
| Traces | Pass-Through, Filter, Enrich, Mask, Sample, Tail, Metrics |

Each agent runs on an isolated Ubuntu c8i.2xlarge. Five offered rates (1k, 10k, 25k, 50k, 125k items/sec), batches of 512, four persistent clients, no compression, five seconds of warm-up, and 30 seconds of measured input per tier. The destination accepts native OTLP/HTTP protobuf or JSON on the same host. CPU and RSS cover the active input window; acknowledgment latency is not end-to-end latency. Direct-to-destination calibration precedes every signal/rate comparison.

Operation checks allow vendor resource/scope metadata differences. They check counts and values, trace identities and parent relationships, requested attribute changes, and complete-trace sampling. Metadata differences remain in the raw captures. Filter drops health traffic; Enrich adds `bench.enriched=yes`; Mask replaces `secret`; Sample keeps about half the complete traces; Tail retains traces containing an error child; Metrics generates counts and latency histograms.

Aggregate sums across host labels. Rollup combines input points using each agent's native 60-second interval behavior. Combined does both. Native event-time and flush-time implementations can produce different output point counts: grouped sums must survive, and the output must actually be reduced. Removing a label without aggregation does not pass. The chart measures native processing costs rather than requiring identical event-time alignment. Drains allow each interval to flush before delivery checks.

Solid bars sustained the offered load and verified delivery. Dashed bars indicate load or delivery issues. N/A means no comparable measurement for the tested configuration, not a vendor capability determination. Unimplemented native adapters remain N/A; missing measurements are never invented. These are fixed-load costs, not a maximum-capacity search. The workload is delta sums and two-span traces; other metric types and repeated-trial distributions are separate work.

## Run and preview

```sh
python3 -m venv /tmp/otlp-venv
/tmp/otlp-venv/bin/pip install -r otlpbench/requirements.txt
/tmp/otlp-venv/bin/python -m unittest otlpbench.test_model -v
bash otlpbench/cloud.sh bindplane
/tmp/otlp-venv/bin/python -m otlpbench.chart otlp-results /tmp/otlp-preview/index.html
python3 -m http.server 8765 --bind 127.0.0.1 --directory /tmp/otlp-preview
```

`OTLP_SIGNALS=metrics` or `traces` runs a signal independently; `OTLP_SCENARIOS` selects comma-separated scenarios. Run each cloud shard from a separate checkout so Terraform state is isolated. Every shard destroys its temporary infrastructure on exit. JSON records the benchmark commit, binary hash and version. Charts embed the data and work offline.

The optional Actions workflow is artifact-only and requires the repository's AWS role; otherwise run cloud shards with your own AWS credentials.

## High request-rate Pass-Through

The [Rust request-rate harness](RPS.md) runs the generator, agent, and sink on separate hosts. It supports configurable requests/sec, points/request, connection counts, concurrency, and repeat trials, with calibration and delivery gates. Use it for 10k/100k requests/sec tests; the fixed item-rate runs above remain separate.
