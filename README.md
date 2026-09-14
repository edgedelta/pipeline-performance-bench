# Pipeline performance bench

A successor to [edgedelta/benchmark](https://github.com/edgedelta/benchmark). Compare HTTP log ingestion by Edge Delta's Go and Rust agents, Cribl, OpenTelemetry Collector, Fluentd, Vector, and Fluent Bit. Source provenance is recorded in [UPSTREAM.md](UPSTREAM.md).

The harness retains the upstream EC2/S3 setup, loadgen 1.1.0 nginx JSON workload, 80/100/120 concurrent workers, one minute per worker setting, and 60-second drain intervals. Agents run sequentially on one Ubuntu 24.04 `c8i.2xlarge` instance. It does not publish releases, deploy a website, or run scheduled cloud benchmarks.

| Agent selector | Agent | Pass-through | Filter | Mask | CSV lookup |
|---|---|---|---|---|---|
| `edgedelta` | Edge Delta (Go) | Yes | Yes | Yes | Yes |
| `red` | Edge Delta (Rust) | Yes | Yes | Yes | Yes |
| `cribl` | Cribl | Yes | Yes | Yes | Yes |
| `otelcol` | OpenTelemetry Collector | Yes | Yes | Yes | N/A |
| `fluentd` | Fluentd | Yes | Yes | Yes | Yes |
| `vector` | Vector 0.55.0 | Yes | Yes | Yes | Yes |
| `fluentbit` | Fluent Bit 5.1.2 | Yes | Yes | N/A | Yes (Lua) |

Fluentd and Fluent Bit are separate competitors. Unsupported cases are skipped and reported as `unsupported`, never as zero throughput. This suite does not implement Fluent Bit regex masking: its bundled Lua string patterns do not match the upstream regex workload. OpenTelemetry's inherited config has no CSV lookup processor.

## Run

Prerequisites: Bash, Python 3, Terraform, jq, curl, SSH/SCP, and AWS credentials with EC2/S3/IAM provisioning access. All cloud runs create billable AWS resources. AWS region remains `us-west-2`; export `AWS_REGION=us-west-2` and `AWS_DEFAULT_REGION=us-west-2` for local runs. No vendor credentials are needed for a dry run or local tests.

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
- Rust source: `RED_SRC_DIR`, default `../red` (the existing `/Users/yildiz/workspace/gocode/src/github.com/edgedelta/red` checkout). The source is built on EC2 with `cargo build --locked --release`. Alternatively set `RED_BINARY` to a prebuilt Linux/amd64 executable. Rust loads the local YAML config.
- Vector and Fluent Bit use pinned release versions in their install scripts and smoke tests. Update both together. Other vendors retain the upstream installation channels; `versions.csv` records the actual version of each selected agent.

Reuse the same environment variables as the existing benchmark:

| Selection | Required environment variables |
|---|---|
| Go Edge Delta | `ED_ORG_ID`, `ED_API_TOKEN` (or `ED_API_TOKEN_CMD` for refreshed tokens) |
| Cribl | `CRIBL_WORKSPACE`, `CRIBL_ORG`, `CRIBL_WORKER_GROUP`, `CRIBL_CLIENT_ID`, `CRIBL_CLIENT_SECRET`, `CRIBL_LEADER_TOKEN` |
| All real runs | Existing AWS profile or AWS credential environment |

Use a dedicated Cribl benchmark worker group. The inherited Cribl adapter installs an input, destination, pipeline and route, then restores the original routes. Do not run another configuration deployment against that worker group during a benchmark. The new suite uses distinct resource names from the old suite, but route restoration still operates on the worker group.

Private rendered configs and generated installers live in ignored `.runtime.*` directories with mode 0700. Templates stay unchanged between runs. These directories and Terraform state can contain credentials; they are not result artifacts. On failure the harness attempts result collection and cleanup. If cleanup fails, retain the runtime directory and `aws_resources` state, resolve the error, and run `terraform -chdir=aws_resources destroy`. Remove private runtime files after cloud cleanup is confirmed.

## Results and interpretation

Each run writes `benchmark_results/<timestamp>/` containing raw `<agent>_<case>.log` files, `versions.csv`, `report.md`, and `data.json`. The summary is deterministic Python; it requires no AI service credentials. Rebuild it with:

```bash
python3 tools/summarize.py benchmark_results/<timestamp>
# Before publishing a complete seven-agent release:
python3 tools/check_results.py benchmark_results/<timestamp>
```

Release tables use the tier with the highest final cumulative average, matching the reference release. Peak, log totals, CPU mean, and peak memory come from that same tier. Multi-process CPU sums per-process means; memory sums per-process peak RSS. Cross-scenario CPU and peak-memory figures average the supported scenarios; throughput per CPU % divides their mean throughput by mean CPU percentage. All tier data and the mean across tiers are retained in data.json. CPU uses 100% per core. Multi-process competitors retain the upstream process-monitoring method, which may omit auxiliary processes. These figures are not complete host/cgroup resource measurements.

Incomplete runs, HTTP send errors, missing statistics, and detected service restarts invalidate a scenario. Missing runs and unsupported cases remain distinct. HTTP acceptance does not prove durable S3 delivery: these configs use different buffering, compression, output schemas, and acknowledgment semantics. Vector writes gzip JSON; Fluent Bit uses gzip JSON with disk-backed S3 staging. The inherited agent configs retain their original output settings. Inspect delivery, queue drain, and transform parity before interpreting results as end-to-end performance or publishing comparisons. Local smoke tests validate sources/transforms with stdout output, plus production config loading; they do not test S3 delivery.

Filter drops events whose `pii.color` is `Green`. Lookup matches `pii.ipv4` against the shared CSV's `ipv4` column and emits `region`/`env`, with miss defaults. Vector uses an indexed enrichment table; Fluent Bit loads the bundled simple unquoted CSV once in Lua. Mask uses the inherited nine regexes in Vector. Inherited vendor implementations vary in which fields they scan. New results are not directly interchangeable with old published results: lookup wiring was corrected in this successor.

The inherited `site/` chart viewer and history utilities now recognize all seven agents. Nothing is automatically published. To preview a real local report:

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

Docker smoke tests validate all Vector/Fluent Bit production configs without AWS networking, then send fixture JSON through HTTP sources and assert pass-through, filter, lookup hit/miss, and nine-field Vector masking behavior. They create temporary containers and remove them afterward. Docker images are pinned to the same versions as native installers. [VALIDATION.md](VALIDATION.md) records the checks performed during implementation.

## GitHub Actions (when a remote is created)

`validate.yml` runs local checks and Docker smoke tests. `benchmark.yml` is manual only and uploads raw logs/reports as workflow artifacts. It has no release, Pages, website, or schedule step.

Configure the original secret names in the new repository (or grant it access to the existing organization secrets): `AWS_BEDROCK_ROLE`, the selected vendor credentials above, and `APP_ID`/`APP_PRIVATE_KEY` for private Rust checkout. GitHub does not expose existing repository secret values for copying. AWS OIDC trust must explicitly permit the new repository, and the workflow uses two-hour sessions and refreshes AWS credentials before infrastructure cleanup. The initial release can use a temporary workflow in the existing benchmark repository so its secrets and OIDC trust remain in place. Inputs are passed through environment variables and validated before use.

Reference docs: [Vector HTTP](https://vector.dev/docs/reference/configuration/sources/http_server/), [Vector S3](https://vector.dev/docs/reference/configuration/sinks/aws_s3/), [Fluent Bit S3](https://docs.fluentbit.io/manual/data-pipeline/outputs/s3), [Fluent Bit Lua](https://docs.fluentbit.io/manual/data-pipeline/filters/lua).
