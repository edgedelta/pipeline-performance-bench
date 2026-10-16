# OTLP metrics and traces preview

This suite runs on a pull-request branch before merge. Dispatch **Validate benchmark harness** with `otlp_benchmark=true` and the PR branch ref. It creates a separate Ubuntu 24.04 `c8i.2xlarge` for each installed agent, uploads evidence, and destroys the instances. It does not create releases, write Pages data, or merge the PR.

## Contracts

| Signal | Scenario | Required behavior |
|---|---|---|
| Both | Pass-Through | Preserve points/spans and their resource/scope identity. |
| Both | Filter | Drop records with route=health (25%). |
| Both | Enrich | Add bench.enriched=yes. |
| Metrics | Aggregate | Sum delta counters across host labels; retain route and 10-second buckets. |
| Metrics | Rollup | Sum 10-second delta counters into aligned 60-second buckets, retaining host and route. |
| Metrics | Combined | Reduce host cardinality and produce 60-second buckets. |
| Traces | Mask | Replace secret attribute with REDACTED. |
| Traces | Sample | Keep approximately 50% of whole traces using trace-ID sampling. |
| Traces | Tail | Retain whole traces containing an ERROR child span, including their OK parents. |
| Traces | Metrics | Generate span/error counts and latency histograms with correct sums and bucket counts. |

Metrics use one delta monotonic sum, 64 hosts, two routes, and eight event-time buckets. Traces contain two SERVER spans each, with IDs, parent relationships, events, links, a secret attribute, and 20ms durations. Only one child in every fourth trace is ERROR. Each correctness fixture is split across two requests to catch per-request-only aggregation and incomplete-trace sampling. Raw sent/received records are retained.

Aggregation is an event-time contract: bucket end timestamps and interval start timestamps are checked. Old event times allow flushes without a minute-long initial alignment wait. Correctness drain is 70 seconds for Rollup/Combined, 25 seconds for Aggregate, and 4 seconds otherwise. Sampling may add the standard OTel `ot=` tracestate member; other span fields must remain unchanged. This is a bounded preview, not a claim that slower-flushing configurations are unsupported.

## Measurements

Persistent OTLP/gRPC input, no compression, four clients, 512 points/spans per request. Native OTLP/HTTP protobuf output goes to the same local destination implementation. This first preview measures fixed offered rates of 1,000 and 10,000 items/sec for 30 seconds after warm-up, with a direct-to-destination calibration at each rate. It is not a maximum-throughput benchmark and is not comparable to the existing Rust-generator log results.

Report fields include accepted input rate, delivered output count, partial rejections/RPC errors, p95 export acknowledgment latency (not end-to-end latency), process-tree CPU cores, and process-tree average/peak RSS. Resource samples cover the sending interval. Correctness failures do not receive performance scores. Output counts and rates flag delivery or input shortfalls. Generator calibration failures suppress measurement.

Status `not_configured` means an adapter is still needed, not that the vendor is incapable. This draft initially exercises all scenarios for OTel and Bindplane, the native Edge Delta scenarios, Fluent Bit trace processing and metric enrichment, Cribl forwarding/basic transforms, and forwarding for Vector/Fluentd. Other transformation adapters remain pending. These gaps must remain visible in the PR report.

The interval processor is tested as a candidate for Rollup. The observed 0.162.0 output combined eight event-time buckets into one flush-time series, which does not satisfy the aligned event-time contract. OTel metricstransform aggregation is confined to an incoming batch; the cross-request fixture checks that limitation. Treat native output captures as evidence rather than assuming similarly named processors are equivalent. Reference docs: [interval](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/processor/intervalprocessor), [metricstransform](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/processor/metricstransformprocessor).

OTel is pinned to 0.162.0 for this preview so rechecks use the same binary. Other installed versions and binary hashes are recorded in the results.

## Local validation

```sh
python3 -m venv /tmp/otlp-venv
/tmp/otlp-venv/bin/pip install -r otlpbench/requirements.txt
/tmp/otlp-venv/bin/python -m unittest otlpbench.test_model -v
/tmp/otlp-venv/bin/python -m otlpbench.runner --vendor bindplane --binary /path/to/observiq-otel-collector --output /tmp/otlp-results
```

The first preview does not yet cover gauges/histogram input workloads, an input batch-size sweep, higher-rate capacity search, repeated trials, or end-to-end latency. Keep the PR draft until the evidence and remaining adapters are reviewed.

The existing AWS role currently trusts only main. Until branch execution is authorized separately, run the PR checkout locally with existing AWS credentials using `bash otlpbench/cloud.sh VENDOR`, which cleans up its temporary resources on exit, and attach its SHA-tagged artifacts to the PR. Do not widen the shared role automatically.
