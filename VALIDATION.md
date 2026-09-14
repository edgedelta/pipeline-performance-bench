# Implementation validation

The [initial release 20260914-083749](https://github.com/edgedelta/pipeline-performance-bench/releases/tag/20260914-083749) was measured on 2026-09-14 by [workflow 34809968062](https://github.com/edgedelta/benchmark/actions/runs/34809968062). All 26 supported scenarios completed on one Ubuntu 24.04 `c8i.2xlarge` instance. Twenty-two recorded no HTTP errors; the four Rust scenarios recorded 181 errors across all tiers (40 pass-through, 88 filter, 25 mask, 28 lookup). Those measurements remain visible with an `errors` status and are excluded from rankings and cross-scenario charts. No scenario reported backpressure.

All seven installed versions and source provenance were recorded. The 31 release assets passed coverage and credential-pattern checks, and uploaded SHA-256 digests matched the local files. AWS cleanup succeeded; the instance, security group, and S3 bucket were verified removed. Temporary GitHub checkout keys, secrets, and the bootstrap branch were removed.

The cloud run exercised native installation and service startup for all seven agents, including a release build of private Rust source. Small S3 samples confirmed observed Rust filtering and masking; the release notes document sample sizes and limitations. This is an HTTP ingestion benchmark, not a complete durable-delivery or semantic-parity audit.

Local implementation checks (2026-09-13, with harness regression checks updated on 2026-09-14):

- Seven Docker integration cases passed: Vector pass-through/filter/mask/lookup and Fluent Bit pass-through/filter/lookup. Each validates the production configuration and checks HTTP behavior with a stdout sink.
- Twelve Python harness tests passed: Bash syntax, credential-free matrix selection from another working directory, invalid selections, unsupported cases, failed/partial log rejection, missing-versus-unsupported reporting, and preservation of completed HTTP-error measurements without ranking or charting them.
- Fourteen inherited Node history/report utility tests passed.
- Native Ubuntu 24.04 Linux/amd64 Vector and Fluent Bit installation scripts passed in Docker; systemctl was stubbed because this container check has no systemd. The cloud run separately exercises service startup.
- Terraform initialization with locked providers and `terraform validate` passed locally; cloud apply and destroy subsequently succeeded in the workflow.
- All YAML/JSON files parsed and staged Git whitespace checks passed.

Images tested:

- `timberio/vector:0.55.0-debian`, digest `sha256:a4be1111b40303524aae2ffb02cd59cef2a4e9753bd13d265bf0233e921828d9`
- `fluent/fluent-bit:5.1.2`, digest `sha256:d792375ca8e53be72fc25716c28f291f32c6fc6f4f31d12d0d14bc78cefe9226`

The local checks do not establish S3 delivery under load or full EC2 performance. The cloud run uses a prebuilt Go release and builds private Rust source on EC2. Initial execution reuses the original benchmark repository’s credentials and AWS trust; credentials and OIDC trust for direct execution in this repository remain to be configured.
