# Trace identifier allocation follow-up

Rust candidate `8c29318` decodes OTLP trace/span/link IDs as shared bytes, then copies IDs of up to 16 bytes inline into native spans. Longer IDs retain owned storage. Native items do not retain input request buffers. The OTLP/gRPC input changes; HTTP decoding and filtering/sampling semantics are unchanged.

Three alternating decoder microbenchmarks measured about 663 ns/span with the standard decoder versus 538 ns/span with shared identifiers (18.8% faster). This microbenchmark uses the system allocator; full scenarios use the production mimalloc build.

## End-to-end comparison

Two 60-second trials per scenario/vendor at 8,000 requests/sec × 512 spans/request, separate c8i.8xlarge load/agent/sink hosts, 64 connections and 1,024 maximum outstanding requests. All agents use OTLP/gRPC input and uncompressed OTLP/HTTP output. Saved Rust baseline was rerun on these same hosts before the candidate.

| Scenario | Saved Rust CPU | New Rust CPU | OTel CPU | Bindplane CPU | Improvement vs saved Rust |
|---|---:|---:|---:|---:|---:|
| Filter | 8.485 | 7.829 | 8.478 | 8.793 | 7.7% |
| Sample | 8.417 | 7.766 | 12.921 | 13.511 | 7.7% |

CPU includes processing through final delivery and is divided by the configured 60-second offered-load window. These results measure this fixture and rate, not maximum throughput.

Filter drops 25% of spans and checks exact output count, payload, parent/child pairing, and 384-span output batches. Sample uses native 50% trace-ID sampling and checks retention, payload, and parent/child fingerprints; these checks do not independently prove the exact retained set or exclude small delivery loss. Input has 256 complete two-span traces per request, unique IDs across requests, and stable resource metadata. Mixed metadata is covered by correctness tests.

Validation: 1,266 library tests passed (seven ignored), 16 native-processing and OTLP integration tests passed, and all-target Clippy passed with existing warnings. New coverage checks full protobuf field equivalence, malformed/truncated input acceptance, short/long IDs, mixed metadata, no retained input frame, gzip, default 4 MB message limit, empty requests and shutdown backpressure.

Profiles run separately after scored trials at 99 Hz with DWARF stacks. The three largest allocator functions account for 24.3% of Filter samples and 22.2% of Sample samples, versus roughly 30% and 28% in the previous profiles. Attribute-map construction and protobuf decoding remain significant costs; these are sampled proportions, not absolute CPU measurements. Exact configs, raw trials, microbenchmarks, profiles, build hashes and measured harness source are included.

Open `index.html` for the interactive report. Draft PRs remain unmerged; public Pages is unchanged.
