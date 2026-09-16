# Fixed-throughput methodology and result contract

The daily suite preserves the 26 supported best-throughput scenarios and their
80/100/120-worker measurements. It schedules up to 130 additional fixed-rate tiers:
each supported agent/scenario at 10,000, 25,000, 50,000, 75,000 and 125,000 **total input
logs/second**. Fixed-rate results are independent measurements, never estimates
from maximum-throughput results. These two workloads are separate experiments.

## Workload and topology

Seven daily jobs run concurrently, each with its own AWS instance and resources.
Within each job, installation happens once. Each scenario is configured once,
then its legacy throughput tiers and ascending fixed rates run sequentially.
The next scenario starts afterward. Every measured tier keeps its own resource
window; throughput-mode samples never substitute for fixed-rate measurements. Direct `run.sh` remains
sequential on one instance; runtime topology records that distinction.

Fixed mode uses 256 workers with one global scheduler. A 1 ms scheduling tick
releases cumulative target tokens, capped at 5 ms of catch-up. A delayed scheduler
records missed tokens; a full worker queue records dropped tokens. Workers never
create rate tokens. The queue is bounded to 256 entries. Requests expired at the
measurement deadline are counted separately. There is no unbounded catch-up burst.

All fixed tiers use the exact bytes in `payloads/fixed-nginx.ndjson` (100 repeated
nginx-shaped JSON events, retained and SHA-256 checked across shards). One line is
one log and one HTTP request. The corpus includes 25% Green filter matches, lookup
hits/misses and PII fields. It is deterministic and differs from the legacy
randomized corpus. Identical inputs do not imply identical product transforms or
output schemas: the inherited semantic limitations still apply.

Each measured tier starts its service, waits for 30 seconds of continuous active
state and listening port, offers warm-up traffic for 10 seconds, drains warm-up
HTTP requests, then measures for 60 seconds. It drains outstanding HTTP requests
within their original 30-second timeouts and observes the service for another
60 seconds before stopping it. Service invocation changes invalidate the tier.
This does **not** prove that agent buffers or S3 writes drained.

Before the first fixed-rate scenario, all five rates are calibrated once on the
instance with the service stopped. The generator is calibrated against a local fast-acknowledgement server using the
same corpus, workers and delivery policy (2-second warm-up, 10-second measure).
The calibration includes server CPU in the generator process. It establishes
source capability in isolation; it does not establish capacity when an agent
competes for host resources. Calibration is reused across scenarios on that
instance. Failed calibration remains an explicit generator-limited outcome.

Retries preserve the existing two-retry, fresh-connection, 10/20 ms backoff policy
inside the original request timeout. Ambiguous requests may be retried, so delivery
is at least once with possible duplicates. HTTP status failures, timeouts and
cancellation are not retried. Fixed mode exposes redirects as invalid endpoints,
rather than following them. No metric claims durable delivery.

## Windows, counters and attainment

- Offered logs are logical requests fully written during the measurement window,
  once per request despite retries. A failed write is not proof of a full offer.
- Acknowledged logs are successful HTTP responses whose bodies were completely
  read within that window. Acknowledgements after the window remain separate.
- Final errors include backpressure (HTTP 429/503); do not add backpressure to
  errors. Final outcomes include completion during HTTP drain. Counters cover
  logical requests dispatched in the phase, not individual retry attempts.
- Scheduled = dispatched + scheduler missed + worker queue dropped + expired
  before dispatch. Dispatched = window acknowledgements + late acknowledgements
  + final errors. Validation checks these identities and retry invariants.
- Resource samples and CPU deltas cover the measurement window, excluding warm-up
  and drain. The actual duration must be within ±2% of its configured duration.

**Sustains target** requires offered rate within ±2% of target; acknowledged rate
at least 98% of target and 98% of actual offered rate; no final errors/backpressure;
valid duration, resources, service continuity and completed HTTP drain. Calibration
must meet the same rate criterion, with scheduler misses at most 2%; the measured
phase must also have no more than 2% scheduler misses.

| Status | Meaning | Release eligibility |
|---|---|---|
| `ok` | Meets the sustained-target criterion | Yes |
| `capacity_limited` | Calibrated source; rejection/failure or acknowledgement shortfall in the colocated setup | Yes, visibly failed attainment; excluded from efficiency comparisons |
| `generator_limited` | Calibration/scheduler failure or inconclusive under-offering without explicit agent rejection | Yes, explicitly failed/uncertain attainment; never an agent-only capacity claim |
| `skipped_after_shortfall` | Higher rate intentionally not tested after the first measured shortfall | Yes, requires a valid earlier shortfall record; no metrics or attainment inferred |
| `invalid` | Missing/broken counters, resource window, service continuity, policy or malformed endpoint/payload evidence | No |
| `missing` | Expected measurement file absent | No |
| `unsupported` | Suite does not implement that agent/scenario | Expected exclusion |
| `not_measured` | Historical format lacks fixed-rate measurements | Historical reports only |

A 4xx response other than 429 is invalid configuration evidence, not a capacity
claim. Request failures and 5xx responses are reported as limits of this tested
setup, not proof of an agent-only CPU bottleneck. Standalone calibration cannot
rule out colocated host contention; unexplained under-offering is conservatively
source-limited. Host busy and generator CPU/RSS counters are retained for diagnosis.

The runner stops higher fixed rates for a scenario after the first measured
`capacity_limited` or `generator_limited` outcome. Higher-rate JSON assets explicitly
reference that measured target and contain no fabricated resource or throughput
measurements. Missing or invalid evidence aborts the run; it cannot justify skips.
Reports show PASS, FAIL (target not sustained), or NOT TESTED alongside the original
diagnostic status, and summarize the highest measured sustained tier. This is not
an exact capacity estimate or proof of backlog stability. If even 10k fails,
highest sustained target is N/A, not zero. Historical files retain all measured tiers.
Release introductions count failures, skips and generator uncertainty explicitly.

Agent backlog before/after and stability are **N/A, not measured**. Client queue
and in-flight counts at the window boundary, late acknowledgements and elapsed
HTTP drain are available. These are not agent backlog or durable-delivery metrics.

## Resource scope and efficiency

Fixed-rate CPU and memory use the entire systemd service cgroup v2, including child
processes. The generator must be in a different cgroup. CPU 100% means one logical
core. CPU mean = change in `cpu.stat` usage_usec / elapsed seconds / 10,000.
Memory uses `memory.current`, including descendants, page cache and charged kernel
memory. MB means 1,000,000 bytes. Average memory integrates approximately 1-second
samples with the trapezoidal rule; peak is the largest sample (not an unsampled
high-water mark). Missing/reset samples invalidate the measurement. Field semantics follow the
[Linux cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).

For each measured agent/scenario/target:

| Metric | Formula | Better direction |
|---|---|---|
| Logs/sec/core | Acknowledged logs/sec / (CPU% / 100) | Higher |
| CPU microseconds/acknowledged log | (CPU% / 100) × 1,000,000 / acknowledged logs/sec | Lower |
| Logs/sec/MB average memory | Acknowledged logs/sec / average memory MB | Higher |

Zero denominators remain N/A. Metrics from failed attainment can describe those
runs but cannot establish equal-throughput resource wins. Cross-agent aggregates
use only pass-through and filter, supported by all seven agents. Each included
agent must sustain both at the selected target. Aggregate ratios divide summed
acknowledged rates by summed measured cores or average memory, on those same
scenarios. No agent gets a different scenario set to improve its aggregate.

Legacy best-throughput CPU and RSS fields remain unchanged in data.json. Legacy
memory was labeled MB by upstream but is MiB (1,048,576 bytes); report labels now
clarify that. Its per-process peaks may occur at different times and auxiliary
processes may be omitted. Do not compare those values directly with fixed cgroup
memory or call legacy averages across differing supported scenarios a ranking.

## Hardware and reproducibility

Runtime inspection captures IMDS instance type/region/AZ, logical CPUs, CPU model,
architecture, sockets/cores/threads, OS-accessible installed memory, OS/kernel,
block-device sizes/types, virtualization and service/generator cgroup limits and
CPU affinities. Effective quotas include ancestors. Published EC2 API fields
provide CPU and memory specifications, network baseline/maximum Gbps, EBS baseline/
maximum Mbps, MB/s and IOPS, and provisioned volume type/GiB/IOPS/MiB/s. Observed
and published values are separate; unavailable fields stay null/N/A. Advertised
bandwidth is not measured bandwidth. No hardware asset retains infrastructure
IDs, hostnames, private addresses, tags, credentials or serial numbers.

The merge/publication gate checks matching corpus, methodology, actual machine
configuration, provisioned storage configuration and service limits. Daily merge
requires schema 3 (including 125k); older result files retain their original target set and can still be summarized without new metrics.

Historical schema-3 full releases retain 203 evidence assets plus SHA256SUMS: 26 legacy logs,
130 fixed tier JSON files (either validated skip records or complete loadgen warm-up and measurement
records), 35 calibration JSON files, seven hardware JSON files, the corpus,
versions.csv, provenance.json, data.json and report.md. Upload verification uses
paginated GitHub asset listings and SHA-256 digests. Synthetic fixtures cannot
pass publication validation. Invalid or incomplete evidence retains workflow shard artifacts and blocks
publication. Valid measured shortfalls and evidence-backed skips may publish,
with failed attainment and any source uncertainty explicitly counted in the
release introduction. They are never advertised as successful target tests.

## Local preview, validation and real collection

These commands create no AWS resources and publish nothing:

```bash
./tools/build_loadgen.sh --test
python3 -m unittest discover -s tests -v
node --test tools/*.test.mjs
python3 tests/fixed_smoke.py
python3 tests/smoke.py
python3 tools/preview_release.py benchmark_results/fixed-preview
```

The preview contains **synthetic fixture numbers** throughout. It exercises the
same concise renderer used for the actual release body, but is not a real
performance comparison. Use a new output directory when regenerating it.

After this change is reviewed and merged to main, this command launches the real
billable daily suite and publishes a dated release only if validation passes:

```bash
gh workflow run benchmark.yml --repo edgedelta/pipeline-performance-bench --ref main
```

The existing daily 09:17 UTC schedule, latest agent installation channels and
seven-agent parallelism are preserved. The job allows 120 minutes for provisioning,
installation and both workloads; timeout/failure still triggers cleanup, with
refreshed AWS credentials. The extended suite duration has not been measured in
AWS yet. Real results must be collected; no fixture or old maximum is substituted.
Historical releases and the website are not changed by local rendering.

Machine comparability requires matching CPU, instance type, region, OS, kernel,
storage and resource limits. OS-accessible MemTotal may differ by at most 64 KiB
when AWS published memory capacities match. Exact observed bytes remain in raw
assets. Without published memory metadata, observed memory must match exactly.

## Reader-facing release notes

The release body shows best-tested throughput, highest sustained fixed targets,
shared hardware once (with explicit differences/N/A), and fully expanded scenario
tables for measured CPU, average memory and throughput per core/MB. Versions
and source are also expanded. Overview tables sort by pass-through descending;
fixed-rate rows group by target descending (125k, 75k, 50k, 25k, 10k), then passing rows by logs/sec/core descending
and failed rows by achieved throughput descending. Ties use agent name. Failure, uncertainty and skipped-target labels remain
visible. Connection recovery, queue/drain diagnostics, detailed reliability,
peak memory and aggregate efficiency stay in `report.md`, `data.json` and raw
assets, linked from the release. The daily publisher and local release preview
use this concise renderer; evidence validation and full assets are unchanged.

Descending target order is presentation only. Benchmark execution still tests
ascending rates and stops higher tiers after a measured shortfall.

Release highlights use 🏆 and bold scenario values for the highest valid
best-tested throughput or sustained target, including exact ties. Fixed-rate
🔹 bold rows identify the highest observed logs/sec/core among passing agents
at each scenario/target (including a sole passing agent). Failed, invalid,
missing, unsupported and skipped outcomes never receive leader highlights.
Selection uses unrounded positive finite measurements; environment uncertainty
remains explicit. These styles affect the release body and its local preview;
raw data and detailed evidence assets retain their original measurements.

Throughput rows sort by pass-through, valid outcomes first. Sustained targets
sort descending by pass-through, then filter, mask and lookup, then agent name.
Fixed-rate targets sort highest first; passing rows sort by CPU efficiency,
then failed rows by achieved throughput, with alphabetical agent ties. Hardware
settings and agent versions sort alphabetically.

## Rust sustained-throughput search (schema 4)

New full runs replace the Go 80/100/120-worker periodic sweep with a bounded
Rust rate search. The existing standard fixed tiers (10k, 25k, 50k, 75k, 125k)
run once per scenario, in ascending order, stopping after the first shortfall.
Their raw measurements are reused directly for the throughput summary:

- If 125k passes, probe 200k, then 250k, stopping on the first shortfall.
- If 10k fails, probe 1k, 2.5k, then 5k, stopping on the first shortfall.
- Otherwise, no extra probes are needed. This is a discrete search, not an exact
  saturation estimate or binary search between the last pass and first failure.
- Short validation runs reuse just 10k/125k; no extra probes or Go sweep run.

All probes use the fixed-tier Rust generator and policy: immutable corpus,
256 workers, one log/request, global rate limit, identical retry semantics,
10-second warm-up, 60-second measurement, 60-second post-load observation,
independent service start/stop and stable startup checks. Each newly needed
probe rate is calibrated once per instance. The same 2% attainment tolerance
and zero final request errors apply. Every retained retry/ambiguity counter and
resource sample remains available. Extra probes can be source-limited; a passing
calibration alone does not isolate colocated source versus agent contention.

The headline is the highest **acknowledged** rate among passing measurements,
not the nominal target or an extrapolated result. Selected CPU, memory and total
acknowledgments come from that exact window. `peak` remains null: there is no
sampled instantaneous peak metric. `scenarios[*].trials` retains every standard
tier and extra probe, including failed and skipped outcomes. The legacy `mem`
field is peak memory converted to MiB for existing consumers; explicit
`average_memory_mb` and `peak_memory_mb` use decimal MB and whole-service cgroups.

Passing the 250k ceiling is marked † (higher capacity not tested). Source
uncertainty is marked ‡. No passing tested tier remains `no_sustained_rate` or
`generator_limited`, with null headline throughput; it does not mean zero
capacity. Missing/incomplete evidence is `missing`/`invalid` and blocks
publication. These measurements remain acknowledged HTTP ingestion, not proven
durable delivery or stable backlog. Historical schema 1–3 results keep their
original methodology and assets; no historical numbers are reinterpreted.

Each supported scenario requires an `<agent>_<scenario>.capacity.json` manifest
with the completed deterministic search policy and probe list. Publication
recomputes the search from raw evidence, checks Rust build/payload/timing/retry
identity, forbids missing or unexplained probes, and requires unchanged resource
limits across fixed tiers and probes. Extra `.fixed.json` and shared
`.calibration.json` files are included in release checksums alongside the
manifest, standard fixed measurements, hardware, versions, provenance, structured
data and detailed report. New suites do not require Go `.log` files, a Go compiler, or a Go generator binary. Scheduled
and manual full runs use this method; release titles and highlighting stay the same.

Create an explicitly synthetic preview without AWS:

```bash
python3 tools/preview_release.py benchmark_results/rust-throughput-preview --rust-throughput
```
