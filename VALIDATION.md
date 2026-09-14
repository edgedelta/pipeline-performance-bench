# Implementation validation

Local implementation checks were completed on 2026-09-13. The initial full cloud run is [workflow 34805173373](https://github.com/edgedelta/benchmark/actions/runs/34805173373); results are published only after its complete matrix passes the release checks.

- Seven Docker integration cases passed: Vector pass-through/filter/mask/lookup and Fluent Bit pass-through/filter/lookup. Each validates the production configuration and checks HTTP behavior with a stdout sink.
- Twelve Python harness tests passed: Bash syntax, credential-free matrix selection from another working directory, invalid selections, unsupported cases, failed/partial log rejection, missing-versus-unsupported reporting, and preservation of completed HTTP-error measurements without ranking or charting them.
- Fourteen inherited Node history/report utility tests passed.
- Native Ubuntu 24.04 Linux/amd64 Vector and Fluent Bit installation scripts passed in Docker; systemctl was stubbed because this container check has no systemd. The cloud run separately exercises service startup.
- Terraform initialization with locked providers and `terraform validate` passed; no plan/apply was run.
- All YAML/JSON files parsed and staged Git whitespace checks passed.

Images tested:

- `timberio/vector:0.55.0-debian`, digest `sha256:a4be1111b40303524aae2ffb02cd59cef2a4e9753bd13d265bf0233e921828d9`
- `fluent/fluent-bit:5.1.2`, digest `sha256:d792375ca8e53be72fc25716c28f291f32c6fc6f4f31d12d0d14bc78cefe9226`

The local checks do not establish S3 delivery under load or full EC2 performance. The cloud run uses a prebuilt Go release and builds private Rust source on EC2. Initial execution reuses the original benchmark repository’s credentials and AWS trust; credentials and OIDC trust for direct execution in this repository remain to be configured.
