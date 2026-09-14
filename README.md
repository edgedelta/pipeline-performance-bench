# Pipeline performance bench

A successor to [edgedelta/benchmark](https://github.com/edgedelta/benchmark). Compare HTTP log ingestion by Edge Delta's Go and Rust agents, Cribl, OpenTelemetry Collector, Fluentd, Vector, and Fluent Bit. Source provenance is recorded in [UPSTREAM.md](UPSTREAM.md).

Initial results: [20260914-083749](https://github.com/edgedelta/pipeline-performance-bench/releases/tag/20260914-083749) — seven agents, 26 measured scenarios, raw logs, recorded versions, source provenance, report, and checksums. The four Rust scenarios recorded HTTP errors; their measured values and error counts are shown explicitly and excluded from rankings.

The harness retains the upstream EC2/S3 setup, loadgen 1.1.0 nginx JSON workload with the connection-retry patch described below, 80/100/120 concurrent workers, one minute per worker setting, and 60-second drain intervals. The daily and manual workflow runs up to 26 agent/scenario jobs concurrently on separate Ubuntu 24.04 `c8i.2xlarge` instances, each with isolated AWS resources. Worker tiers run sequentially within each scenario job. A direct `run.sh` invocation remains sequential on one instance. Successful full workflow runs publish dated releases automatically.

| Agent selector | Agent | Pass-through | Filter | Mask | CSV lookup |
|---|---|---|---|---|---|
| `edgedelta` | Edge Delta (Go) | Yes | Yes | Yes | Yes |
| `red` | Edge Delta (Rust) | Yes | Yes | Yes | Yes |
| `cribl` | Cribl | Yes | Yes | Yes | Yes |
| `otelcol` | OpenTelemetry Collector | Yes | Yes | Yes | N/A |
| `fluentd` | Fluentd | Yes | Yes | Yes | Yes |
| `vector` | Vector | Yes | Yes | Yes | Yes |
| `fluentbit` | Fluent Bit | Yes | Yes | N/A | Yes (Lua) |

Fluentd and Fluent Bit are separate competitors. Unsupported cases are skipped and reported as `unsupported`, never as zero throughput. This suite does not implement Fluent Bit regex masking: its bundled Lua string patterns do not match the upstream regex workload. OpenTelemetry's inherited config has no CSV lookup processor.

## Run

Prerequisites: Bash, Python 3, Go 1.26.0, Git, Terraform, jq, curl, SSH/SCP, and AWS credentials with EC2/S3/IAM provisioning access. All cloud runs create billable AWS resources. AWS region remains `us-west-2`; export `AWS_REGION=us-west-2` and `AWS_DEFAULT_REGION=us-west-2` for local runs. No vendor credentials are needed for a dry run or local tests.

```bash
./run.sh --dry-run
./run.sh --dry-run --vendors vector,fluentbit,red --cases filter,lookup
./run.sh --vendors vector,fluentbit
./run.sh --vendors edgedelta,red,cribl,otelcol,fluentd,vector,fluentbit
```

Lists accept commas or spaces. `passthrough` aliases `pass-through`. The script works from any working directory. A real run of all 26 supported scenarios takes several hours including installation/build time.

## Agent sources and credentials

Agent source stays in its own repository; proprietary agent code and credentials are not copied into this repository.

- Go source: `../edgedelta` (the existing `/Users/yildiz/workspace/gocode/src/github.com/edgedelta/edgedelta` checkout). By default the inherited installer uses the candidate release. Set `ED_BINARY` to an existing Linux/amd64 agent binary from that checkout to replace the installed executable before timing. The Go agent still needs its cloud pipeline credentials.
- Rust defaults to the latest stable Linux/amd64 release from `release.edgedelta.com/red`, verified against its published SHA-256. Set `RED_VERSION` to pin a stable version, or `RED_BINARY` to supply a prebuilt executable. Source compilation is opt-in with `RED_BUILD_FROM_SOURCE=1` and `RED_SRC_DIR` (default `../red`). Rust loads the local YAML config.
- Agents resolve their current installation versions on every run; `versions.csv` records the actual version of each selected agent. See Daily releases below for the channel used by each vendor.

Reuse the same environment variables as the existing benchmark:

| Selection | Required environment variables |
|---|---|
| Go Edge Delta | `ED_ORG_ID`, `ED_API_TOKEN` (or `ED_API_TOKEN_CMD` for refreshed tokens) |
| Cribl | `CRIBL_WORKSPACE`, `CRIBL_ORG`, `CRIBL_WORKER_GROUP`, `CRIBL_CLIENT_ID`, `CRIBL_CLIENT_SECRET`, `CRIBL_LEADER_TOKEN` |
| All real runs | Existing AWS profile or AWS credential environment |

Use a dedicated Cribl benchmark worker group. The inherited Cribl adapter installs an input, destination, pipeline and route, then restores the original routes. Do not run another configuration deployment against that worker group during a benchmark. The new suite uses distinct resource names from the old suite, but route restoration still operates on the worker group.

Private rendered configs and generated installers live in ignored `.runtime.*` directories with mode 0700. Templates stay unchanged between runs. These directories and Terraform state can contain credentials; they are not result artifacts. On failure the harness attempts result collection and cleanup. If cleanup fails, retain the runtime directory and `aws_resources` state, resolve the error, and run `terraform -chdir=aws_resources destroy`. Remove private runtime files after cloud cleanup is confirmed.

## Loadgen connection recovery

Before creating AWS resources, `tools/build_loadgen.sh` builds Linux/amd64 loadgen from upstream commit `801c3c369a0e8ff6f40a0af21aa5203f3689d65d` (v1.1.0) plus [the retry patch](patches/loadgen-retry.patch). This is a local patched build, not a published loadgen release. Terraform uploads that executable; every agent receives the same policy. Results record the source commit, patch and executable SHA-256, Go version, and policy. No agent build is involved in this step.

The benchmark explicitly enables `--max-retries 2 --retry-ambiguous`. Connection failures may receive two additional attempts on fresh connections, with 10/20 ms backoff inside the original 30-second request timeout. HTTP error responses, timeouts, and cancellation are not retried. A response whose body cannot be read completely remains a failure.

Delivery uses at-least-once semantics with possible duplicates and remaining failures. An EOF after sending a POST does not reveal whether the server accepted it. Retrying may therefore send the same batch twice; the benchmark does not claim deduplication or exactly-once delivery. Loadgen defaults to **not** retrying ambiguous requests unless explicitly enabled.

`errors` counts final failed logical requests, while `connection_errors`, `retry_attempts`, `recovered_requests`, and `ambiguous_deliveries` expose recovery separately. Ambiguous deliveries count each affected logical request once, even if it later succeeds. They are neither confirmed losses nor confirmed duplicates. These counters cover failures visible to the retry wrapper; Go can also recover safe failures internally. Acknowledged batches count once toward logs/sec, including retry time (this benchmark sends one log per batch). Recovered failures remain eligible for ranking; final failures do not. Old results have N/A recovery counters and are not reclassified.

Local verification only, without AWS resources:

```bash
./tools/build_loadgen.sh --test
```

## Results and interpretation

Each run writes `benchmark_results/<timestamp>/` containing raw `<agent>_<case>.log` files, `versions.csv`, `report.md`, and `data.json`. The summary is deterministic Python; it requires no AI service credentials. Rebuild it with:

```bash
python3 tools/summarize.py benchmark_results/<timestamp>
# Before publishing a complete seven-agent release:
python3 tools/check_results.py benchmark_results/<timestamp>
```

Release tables use the tier with the highest final cumulative average, matching the reference release. Peak, log totals, CPU mean, and peak memory come from that same tier. Multi-process CPU sums per-process means; memory sums per-process peak RSS. Cross-scenario CPU and peak-memory figures average the supported scenarios; throughput per CPU % divides their mean throughput by mean CPU percentage. All tier data and the mean across tiers are retained in data.json. CPU uses 100% per core. Multi-process competitors retain the upstream process-monitoring method, which may omit auxiliary processes. These figures are not complete host/cgroup resource measurements.

Incomplete runs, missing statistics, and detected service restarts invalidate a scenario. Completed measurements with unrecovered HTTP send errors are retained with an `errors` status and reliability counts; they are excluded from ranks and cross-scenario charts. Missing runs and unsupported cases remain distinct. HTTP acceptance does not prove durable S3 delivery: these configs use different buffering, compression, output schemas, and acknowledgment semantics. Vector writes gzip JSON; Fluent Bit uses gzip JSON with disk-backed S3 staging. The inherited agent configs retain their original output settings. Inspect delivery, queue drain, and transform parity before interpreting results as end-to-end performance or publishing comparisons. Local smoke tests validate sources/transforms with stdout output, plus production config loading; they do not test S3 delivery.

Filter drops events whose `pii.color` is `Green`. Lookup matches `pii.ipv4` against the shared CSV's `ipv4` column and emits `region`/`env`, with miss defaults. Vector uses an indexed enrichment table; Fluent Bit loads the bundled simple unquoted CSV once in Lua. Mask uses the inherited nine regexes in Vector. Inherited vendor implementations vary in which fields they scan. New results are not directly interchangeable with old published results: lookup wiring was corrected in this successor.

The inherited `site/` chart viewer and history utilities now recognize all seven agents. Daily full runs publish GitHub releases; website publishing remains separate. To preview a real local report:

```bash
mkdir -p site/data
node tools/merge-history.mjs site/data/history.json benchmark_results/<timestamp>/data.json site/data/history.json <timestamp>
python3 -m http.server 8000 --directory site
```

## Validation

```bash
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
node --test tools/*.test.mjs
python3 tests/smoke.py
```

Docker smoke tests validate all Vector/Fluent Bit production configs without AWS networking, then send fixture JSON through HTTP sources and assert pass-through, filter, lookup hit/miss, and nine-field Vector masking behavior. They create temporary containers and remove them afterward. Docker smoke tests pull the latest stable images before running. [VALIDATION.md](VALIDATION.md) records the checks performed during implementation.

## GitHub Actions

`validate.yml` runs local checks and Docker smoke tests. `benchmark.yml` runs daily and supports manual dispatch. Full successful suites publish dated GitHub releases; all runs upload available artifacts. It does not update Pages or the website.

Configure the original secret names in the new repository (or grant it access to the existing organization secrets): `AWS_BEDROCK_ROLE`, the selected vendor credentials above, for the selected agents. Released RED binaries require no private checkout credentials. GitHub does not expose existing repository secret values for copying. AWS OIDC trust must explicitly permit the new repository, and the workflow uses two-hour sessions and refreshes AWS credentials before infrastructure cleanup. The initial release used [a temporary workflow in the existing benchmark repository](https://github.com/edgedelta/benchmark/actions/runs/34809968062), reusing its secrets and OIDC trust. Temporary read-only checkout access and the bootstrap branch were removed after publication. Inputs are passed through environment variables and validated before use.

Reference docs: [Vector HTTP](https://vector.dev/docs/reference/configuration/sources/http_server/), [Vector S3](https://vector.dev/docs/reference/configuration/sinks/aws_s3/), [Fluent Bit S3](https://docs.fluentbit.io/manual/data-pipeline/outputs/s3), [Fluent Bit Lua](https://docs.fluentbit.io/manual/data-pipeline/filters/lua).

## Daily releases

The benchmark workflow runs daily at **09:17 UTC**. Each supported agent/scenario pair gets a separate
EC2 instance: 26 jobs, with up to 26 running concurrently. Each job runs its
80/100/120-worker tiers sequentially and removes its own resources when done.
Actual concurrency is subject to GitHub runner and AWS account capacity. Each successful full suite
publishes a new UTC-dated release, including the measured versions, report,
raw logs, provenance, and verified checksums. Previous releases remain intact.
Partial manual runs produce workflow artifacts only. Failed runs do not publish
results as a successful release; AWS teardown still runs for each agent.

To switch to Mondays, change `.github/workflows/benchmark.yml` from
`17 9 * * *` to `17 9 * * 1`. GitHub schedules use UTC and may start late.

Every run installs fresh agents without fixed agent version numbers:

| Agent | Current installation channel |
|---|---|
| Edge Delta Go | Latest candidate installer (the existing Go benchmark channel) |
| Edge Delta Rust | Latest stable released binary, checksum verified |
| Vector | Latest stable GitHub release |
| Fluent Bit | Latest package in the vendor's Ubuntu repository |
| Fluentd | Latest fluent-package generation, then latest stable Fluentd gem |
| OpenTelemetry Collector | Latest stable contrib GitHub release |
| Cribl | Current installer supplied by the configured Cribl Cloud workspace |

Cribl's available version follows the Cloud workspace rollout. Exact installed
versions are recorded in every release; installation failures do not fall back
to a pinned version. The load generator and runner tooling remain controlled
benchmark dependencies, separate from the agents under test.

Scenario isolation: Edge Delta Go creates a uniquely tagged pipeline for each
instance. Each Cribl job creates a unique temporary self-managed Edge fleet;
its inputs, routes, pipeline, and destination never touch the shared fleet.
Fleet deletion runs after AWS teardown, including when a benchmark fails.
Results must contain 26 distinct instances, distinct Cribl fleet IDs, and a
consistent installed agent version across each vendor's scenarios before a
full release can be published. This is a methodology change from prior runs:
instances are fresh for each scenario rather than reused across scenarios.
