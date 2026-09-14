# Implementation validation

Validated locally on 2026-09-13. No AWS benchmark was executed and no new performance results were produced or published.

- Seven Docker integration cases passed: Vector pass-through/filter/mask/lookup and Fluent Bit pass-through/filter/lookup. Each validates the production configuration and checks HTTP behavior with a stdout sink.
- Ten Python harness tests passed: Bash syntax, credential-free matrix selection from another working directory, invalid selections, unsupported cases, failed/partial log rejection, and missing-versus-unsupported reporting.
- Fourteen inherited Node history/report utility tests passed.
- Native Ubuntu 24.04 Linux/amd64 Vector and Fluent Bit installation scripts passed in Docker; systemctl was stubbed because this container check has no systemd. Cloud service startup is verified by the benchmark run.
- Terraform initialization with locked providers and `terraform validate` passed; no plan/apply was run.
- All YAML/JSON files parsed and staged Git whitespace checks passed.

Images tested:

- `timberio/vector:0.55.0-debian`, digest `sha256:a4be1111b40303524aae2ffb02cd59cef2a4e9753bd13d265bf0233e921828d9`
- `fluent/fluent-bit:5.1.2`, digest `sha256:d792375ca8e53be72fc25716c28f291f32c6fc6f4f31d12d0d14bc78cefe9226`

Not verified here: native Ubuntu package installation, private Go/Rust source builds, cloud control-plane APIs, S3 delivery under load, full EC2 performance matrix, or GitHub OIDC/secrets in a future remote repository. Those require an actual cloud run.
