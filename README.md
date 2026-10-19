# Pipeline performance bench

A successor to [edgedelta/benchmark](https://github.com/edgedelta/benchmark). Compare HTTP log ingestion by Edge Delta's Go and Rust agents, Cribl, OpenTelemetry Collector, Fluentd, Vector (Datadog), Bindplane (Dynatrace), and Fluent Bit. Source provenance is recorded in [UPSTREAM.md](UPSTREAM.md).

Initial results: [20260914-083749](https://github.com/edgedelta/pipeline-performance-bench/releases/tag/20260914-083749) — seven agents, 26 measured scenarios, raw logs, recorded versions, source provenance, report, and checksums. The four Rust scenarios recorded HTTP errors; their measured values and error counts are shown explicitly and excluded from rankings.

The harness retains the EC2/S3 setup and now uses the Rust load generator for both fixed-rate resource measurements and best sustained throughput. Every measurement uses 256 workers, the same immutable JSON corpus, a global rate limiter and a 60-second measurement window. The workflow runs up to eight agents concurrently on separate Ubuntu 24.04 `c8i.2xlarge` instances, each with isolated AWS resources. Cases and tiers run sequentially within each agent job. A direct `run.sh` invocation remains sequential on one instance. The workflow runs daily and supports manual dispatch; complete validated suites publish dated releases.

| Agent selector | Agent | Pass-through | Filter | Mask | CSV lookup |
|---|---|---|---|---|---|
| `edgedelta` | Edge Delta (Go) | Yes | Yes | Yes | Yes |
| `red` | Edge Delta (Rust) | Yes | Yes | Yes | Yes |
| `cribl` | Cribl | Yes | Yes | Yes | Yes |
| `otelcol` | OpenTelemetry Collector | Yes | Yes | Yes | N/A |
| `fluentd` | Fluentd | Yes | Yes | Yes | Yes |
| `vector` | Vector (Datadog) | Yes | Yes | Yes | Yes |
| `bindplane` | Bindplane (Dynatrace) | Yes | Yes | Yes | Yes |
| `fluentbit` | Fluent Bit | Yes | Yes | N/A | Yes (Lua) |

Fluentd and Fluent Bit are separate competitors. Unsupported cases are skipped and reported as `unsupported`, never as zero throughput. This suite does not implement Fluent Bit regex masking: its bundled Lua string patterns do not match the upstream regex workload. OpenTelemetry's inherited config has no CSV lookup processor.

## Run

Prerequisites: Ubuntu 24.04 x86_64 with Rust 1.98.0 (or a matching prebuilt CI generator bundle), Bash, Python 3, Git, Terraform, jq, curl, SSH/SCP, and AWS credentials with EC2/S3/IAM provisioning access. All cloud runs create billable AWS resources. AWS region remains `us-west-2`; export `AWS_REGION=us-west-2` and `AWS_DEFAULT_REGION=us-west-2` for local runs. No vendor credentials are needed for a dry run or local tests.

```bash
./run.sh --dry-run
./run.sh --dry-run --vendors vector,fluentbit,red --cases filter,lookup
./run.sh --vendors vector,fluentbit
./run.sh --vendors edgedelta,red,cribl,otelcol,fluentd,vector,fluentbit,bindplane
```

Lists accept commas or spaces. `passthrough` aliases `pass-through`. The script works from any working directory. A real run of all 30 supported scenarios takes several hours including installation/build time.

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

Before creating AWS resources, `tools/build_generators.sh` builds the Rust generator once; the daily workflow shares the verified Rust-only bundle across all agent jobs. It neither installs Go nor builds, uploads or installs the Go load generator. No compiler is installed on EC2. Results record Rust compiler/version, executable and source SHA-256 and delivery policy. The old Go build/comparison scripts remain available for explicit local historical comparisons; they are outside the daily and CI paths. No agent build is involved in this step.

The benchmark explicitly enables `--max-retries 2 --retry-ambiguous`. Connection failures may receive two additional attempts on fresh connections, with 10/20 ms backoff inside the original 30-second request timeout. HTTP error responses, timeouts, and cancellation are not retried. A response whose body cannot be read completely remains a failure.

Delivery uses at-least-once semantics with possible duplicates and remaining failures. An EOF after sending a POST does not reveal whether the server accepted it. Retrying may therefore send the same batch twice; the benchmark does not claim deduplication or exactly-once delivery. Loadgen defaults to **not** retrying ambiguous requests unless explicitly enabled.

`errors` counts final failed logical requests, while `connection_errors`, `retry_attempts`, `recovered_requests`, and `ambiguous_deliveries` expose recovery separately. Ambiguous deliveries count each affected logical request once, even if it later succeeds. They are neither confirmed losses nor confirmed duplicates. These counters cover failures visible to the retry wrapper; Go can also recover safe failures internally. Acknowledged batches count once toward logs/sec, including retry time (this benchmark sends one log per batch). Recovered failures remain eligible for ranking; final failures do not. Old results have N/A recovery counters and are not reclassified.

Local verification only, without AWS resources:

```bash
cargo +1.98.0 test --locked --manifest-path loadgen-rust/Cargo.toml
```

## Fixed-throughput resource comparisons

The daily workflow measures every supported agent/scenario at **10,000, 25,000, 50,000, 75,000 and 125,000 total input logs/sec**, with a global rate limiter. Reports include whole-service CPU, average and sampled peak memory, throughput per core and per MB, target attainment, delivery counters, client drain measurements and observed/published AWS hardware specifications. These are new measured experiments, not extrapolations from best throughput. See [the methodology, statuses, asset contract and local preview commands](docs/fixed-throughput.md).

## Results and interpretation

Each new run writes `benchmark_results/<timestamp>/` containing raw `.fixed.json` measurements, `.calibration.json` source checks, `.capacity.json` search manifests, `versions.csv`, `report.md`, and `data.json`. Historical runs retain their original `.log` evidence. The summary is deterministic Python; it requires no AI service credentials. Rebuild it with:

```bash
python3 tools/summarize.py benchmark_results/<timestamp>
# Before publishing a complete eight-agent release:
python3 tools/check_results.py benchmark_results/<timestamp>
```

New releases (provenance schema 4) report **best sustained measured throughput** from the Rust worker generator. The five standard fixed-rate tiers are reused without rerunning them. If 125k passes, the search probes 200k then 250k; if 10k fails, it probes 1k, 2.5k then 5k. Each extra ladder stops on its first shortfall. The highest acknowledged rate among passing measurements supplies throughput, CPU and memory; no peak-throughput metric is invented. Passing the ceiling establishes only a tested lower bound on capacity. Short runs reuse their two fixed-rate measurements without additional probes.

All measurements use the same immutable corpus, 256 Rust workers, global rate limiter, retries, 10-second warm-up, 60-second measurement and 60-second post-load observation. CPU 100% means one logical core; agent memory is whole-service cgroup usage in decimal MB. The same raw fixed-tier record supplies both the resource and throughput summaries. Historical Go results keep their original three-worker-sweep interpretation and are not directly comparable with the new method.

Incomplete evidence, missing probes and service restarts block publication. Measured capacity shortfalls, source limitations and no passing tested tier remain explicit outcomes; they are never substituted with zero capacity. HTTP acceptance does not prove durable S3 delivery or stable agent backlog. Pipeline implementations and buffering differ by product. See [the rate-search method and raw evidence contract](docs/fixed-throughput.md#rust-sustained-throughput-search-schema-4).

Filter drops events whose `pii.color` is `Green`. Lookup matches `pii.ipv4` against the shared CSV's `ipv4` column and emits `region`/`env`, with miss defaults. Vector uses an indexed enrichment table; Fluent Bit loads the bundled simple unquoted CSV once in Lua. Mask uses the inherited nine regexes in Vector. Inherited vendor implementations vary in which fields they scan. New results are not directly interchangeable with old published results: lookup wiring was corrected in this successor.

The `site/` chart viewer is published to GitHub Pages by `.github/workflows/publish-pages.yml` after each successful benchmark workflow run, on release publication, or manually. It rebuilds `data/history.json` from every release's `data.json`, keeping only the summary fields the page reads and skipping the earlier Go-loadgen `best-tier` releases, which are not comparable. The default **By tier** view shows logs/sec per core, logs/sec per MB, CPU cores, memory or logs/sec reached at a chosen load (Highest = 125k down to Lowest = 10k logs/sec), best result on the left. Agents that fell short of that load are drawn as dashed bars showing what they reached. **Trend** plots the same metric and load for one scenario across daily runs, marking agent version changes. Views are linkable, e.g. `?view=trend&metric=cpu&tier=2&scenario=1` (tier index 0 = lowest load). To build the same page locally:

```bash
tools/build_pages.sh /tmp/bench-site
python3 -m http.server 8000 --directory /tmp/bench-site
```

To preview one local report instead:

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
python3 tests/fixed_smoke.py
python3 tests/smoke.py
```

Docker smoke tests validate all Vector/Fluent Bit production configs without AWS networking, then send fixture JSON through HTTP sources and assert pass-through, filter, lookup hit/miss, and nine-field Vector masking behavior. They create temporary containers and remove them afterward. Docker smoke tests pull the latest stable images before running. [VALIDATION.md](VALIDATION.md) records the checks performed during implementation.

## GitHub Actions

`validate.yml` runs local checks and Docker smoke tests. `benchmark.yml` runs daily and supports manual dispatch. Full successful suites publish dated GitHub releases; all runs upload available artifacts. It does not update Pages or the website.

Configure the original secret names in the new repository (or grant it access to the existing organization secrets): `AWS_BEDROCK_ROLE`, the selected vendor credentials above, for the selected agents. Released RED binaries require no private checkout credentials. GitHub does not expose existing repository secret values for copying. AWS OIDC trust must explicitly permit the new repository, and the workflow uses two-hour sessions and refreshes AWS credentials before infrastructure cleanup. The initial release used [a temporary workflow in the existing benchmark repository](https://github.com/edgedelta/benchmark/actions/runs/34809968062), reusing its secrets and OIDC trust. Temporary read-only checkout access and the bootstrap branch were removed after publication. Inputs are passed through environment variables and validated before use.

Reference docs: [Vector HTTP](https://vector.dev/docs/reference/configuration/sources/http_server/), [Vector S3](https://vector.dev/docs/reference/configuration/sinks/aws_s3/), [Fluent Bit S3](https://docs.fluentbit.io/manual/data-pipeline/outputs/s3), [Fluent Bit Lua](https://docs.fluentbit.io/manual/data-pipeline/filters/lua).

## Daily releases

The benchmark workflow runs daily at **09:17 UTC**. Each agent gets a separate
EC2 instance, and all eight jobs run concurrently. Each complete validated full suite
publishes a new UTC-dated release, including the measured versions, report,
raw logs, provenance, and verified checksums. Previous releases remain intact.
Partial manual runs produce workflow artifacts only. Invalid, incomplete and generator-limited runs do not publish
as complete suites; measured capacity limits remain visible without claiming target attainment; AWS teardown still runs for each agent.

To switch to Mondays, change `.github/workflows/benchmark.yml` from
`17 9 * * *` to `17 9 * * 1`. GitHub schedules use UTC and may start late.

Each logs run installs fresh agents using these channels:

| Agent | Current installation channel |
|---|---|
| Edge Delta Go | Latest candidate installer (the existing Go benchmark channel) |
| Edge Delta Rust | Latest qualified candidate, resolved once and checksum verified for all three signals |
| Vector (Datadog) | Latest stable GitHub release |
| Bindplane (Dynatrace) | Latest stable Bindplane collector GitHub release, checksum verified |
| Fluent Bit | Latest package in the vendor's Ubuntu repository |
| Fluentd | Latest fluent-package generation, then latest stable Fluentd gem |
| OpenTelemetry Collector | Latest stable contrib GitHub release |
| Cribl | Current installer supplied by the configured Cribl Cloud workspace |

Cribl's available version follows the Cloud workspace rollout. Exact installed
versions are recorded in every release; installation failures do not fall back
to a pinned version. The load generator and runner tooling remain controlled
benchmark dependencies, separate from the agents under test.

### Comparing load generators locally

The daily [Rust fixed-rate generator](docs/rust-loadgen.md) implements the same HTTP workload and accounting as Go. Run `./tools/compare_loadgens_local.sh` to build both and measure them against a common local receiver at 25k, 75k, 100k and 200k logs/sec. This does not create AWS resources or change the daily benchmark generator.

### Short validation run

Use workflow input `profile=short` (or `./run.sh --profile short`) for pass-through-only validation across the selected agents at 10k and 125k. It keeps 60-second fixed-rate measurement windows, reuses them for the throughput summary, omits extra capacity probes, and normally takes about 8–12 minutes including setup. Short results are labeled validation artifacts and cannot publish a benchmark release. The scheduled job keeps `profile=full`. See [the validation gate and commands](docs/rust-loadgen.md#short-aws-validation-before-a-full-run).

### Bindplane collector

The `bindplane` adapter runs the standalone [Bindplane distribution of OpenTelemetry](https://github.com/observIQ/bindplane-otel-collector) without a management server. Pass-through, filter and mask use the same processors as the OTel comparison; CSV lookup uses Bindplane’s lookup processor with `Unknown` miss defaults. Historical runs without Bindplane measurements display N/A; results are never backfilled from another collector. Run `./run.sh --dry-run --vendors bindplane` to inspect its four scenarios.

Validate an unpacked official Bindplane release locally with `python3 tests/bindplane_smoke.py /path/to/observiq-otel-collector`. This checks production-config startup and pass-through, filter, nine-field masking, and CSV hit/miss behavior through its HTTP receiver using a local file sink.

### Signal pages

The static site has separate `/logs/`, `/metrics/` and `/traces/` routes with shared navigation and styling. The existing root URL continues to show logs. Five-tier ladders use Lowest, Low, Medium, High and Highest; four-tier ladders omit Lowest. Each page shows its actual input rate because named loads are relative to that signal.

`tools/build_pages.sh` builds these routes. Logs use release history; metrics and traces reuse the saved reports selected in `tools/build_signal_pages.py`, with their measured versions and run dates. Updating presentation does not run benchmarks or change measurements. For a local preview, copy `site/` into an output directory, provide its existing `data/history.json`, then run `python3 tools/build_signal_pages.py <output-dir>` and serve that directory.

Saved OTLP datasets and provenance live in [`data/otlp`](data/otlp/README.md). Historical configs, logs, profiles and generated previews are retained in the linked downloadable evidence archive.

### Daily logs, metrics and traces

The daily and manual `Pipeline performance bench` workflow runs all three signals in parallel after building the Rust generators and resolving one qualified Rust candidate. Logs retain eight isolated vendor jobs. Metrics and traces each have three parallel vendor jobs (Rust, OTel and Bindplane), for six OTLP jobs total. Every job uses its own agent, generator and sink hosts; scenarios and loads run sequentially within each vendor job. The report requires every vendor shard and validates matching build provenance before combining results. Metrics use 1k/2k/4k/8k requests/sec and traces use 100/200/300/500, both with 512 items/request and one 60-second trial per case.

A manual full run on a PR branch runs the same workloads and saves review artifacts without publishing releases or Pages. The short profile reduces logs to their validation cases and OTLP to the lowest tier with ten-second trials. On main, full runs publish log results and a checksum-verified OTLP pair with raw evidence. Pages loads the latest published OTLP pair, falling back to the saved datasets only until the first daily pair exists. Invalid/missing cases prevent OTLP publication; measured capacity shortfalls remain visible.

Each cloud job refreshes AWS credentials and destroys its own resources even after failure. Trigger before merge with `gh workflow run benchmark.yml --ref <branch> -f profile=full`, then inspect all log shards, both OTLP jobs, the combined reports and cleanup before merging.

The OTLP comparison currently holds OTel Collector at 0.162.0 and Bindplane at 1.110.1 for continuity with the saved ladders. Their actual versions are recorded in every run. Rust follows the qualified candidate channel shared by all three signals.

The [Ladder page](https://edgedelta.github.io/pipeline-performance-bench/ladder/) shows one load-ladder chart per scenario for logs, metrics and traces. It uses the same published datasets as the signal pages, with vendor markers, load-shortfall indicators and light/dark themes. Pages builds refresh it automatically; no additional benchmark run is needed.
