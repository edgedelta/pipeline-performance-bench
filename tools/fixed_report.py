"""Markdown used identically in local reports and the daily release body."""
from fixed import rates_for


def val(x, digits=2):
    if x is None: return 'N/A'
    if isinstance(x, bool): return 'Yes' if x else 'No'
    if isinstance(x, (float,int)): return f'{x:,.{digits}f}'
    return str(x).replace('|', '\\|').replace('\n', ' ')


def table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---']*len(headers)) + '|'] + ['| ' + ' | '.join(str(c) for c in row) + ' |' for row in rows] + ['']


def hardware_report(data, vendors):
    lines = ['## Hardware and environment specifications', '', 'Observed values come from each running instance (IMDSv2, lscpu, /proc, OS, block-device and cgroup inspection). AWS API values are published specifications/configuration, not measured bandwidth. N/A means unavailable. Hardware raw JSON is retained without instance IDs, hostnames, IPs or volume IDs.', '']
    rows = []; storage = []; limits = []; generator = []
    for v, (_, name) in vendors.items():
        h = data['hardware'][v]; runtime = h.get('runtime', {}); o = runtime.get('observed', {}); p = h.get('published', {})
        rows.append([name, val(o.get('instance_type')), val(o.get('region')) + ' / ' + val(o.get('availability_zone')), val(o.get('logical_cpus'),0), val(o.get('cpu_model')), val(o.get('architecture')), val(o.get('cores_per_socket')) + ' / ' + val(o.get('sockets')) + ' / ' + val(o.get('threads_per_core')), val(o.get('installed_memory_bytes')/1e9 if o.get('installed_memory_bytes') else None) + ' GB', val(o.get('os')), val(o.get('kernel'))])
        disks = o.get('storage_devices') or []
        observed_storage = '; '.join(f"{val(d.get('model'))}: {val(d.get('size')/1e9 if isinstance(d.get('size'), (int,float)) else None)} GB ({val(d.get('type'))})" for d in disks if d.get('type') == 'disk') or 'N/A'
        volumes = '; '.join(f"{val(d.get('VolumeType'))}, {val(d.get('Size'),0)} GiB, {val(d.get('Iops'),0)} IOPS, {val(d.get('Throughput'))} MiB/s" for d in p.get('volumes') or []) or 'N/A'
        net = p.get('network') or {}; cards = net.get('cards') or []
        network = '; '.join(f"{val(c.get('BaselineBandwidthInGbps'))} / {val(c.get('PeakBandwidthInGbps'))} Gbps" for c in cards) or 'N/A'
        e = p.get('ebs') or {}
        ebs = f"{val(e.get('BaselineBandwidthInMbps'))} / {val(e.get('MaximumBandwidthInMbps'))} Mbps; {val(e.get('BaselineThroughputInMBps'))} / {val(e.get('MaximumThroughputInMBps'))} MB/s; {val(e.get('BaselineIops'),0)} / {val(e.get('MaximumIops'),0)} IOPS"
        storage.append([name, observed_storage, volumes, network + '; ' + val(net.get('description')), ebs])
        tier_limits = [t.get('limits') for k,t in data['fixed_throughput']['tiers'].items() if k.startswith(v+'/') and t.get('limits')]
        unique = {__import__('json').dumps(l,sort_keys=True) for l in tier_limits}
        l = tier_limits[0] if len(unique) == 1 else {}
        cpu = 'Unlimited quota' if l.get('unlimited_cpu_quota') else val(l.get('effective_cpu_quota_cores')) + ' cores'
        memory = 'Unlimited' if l.get('unlimited_memory') else val(l.get('effective_memory_limit_bytes')/1e6 if l.get('effective_memory_limit_bytes') is not None else None) + ' MB'
        limits.append([name, cpu, val(l.get('cpuset_cpus_effective')) + '; process affinity: ' + val(l.get('main_process_cpu_affinity')), memory, val(l.get('memory_high_bytes')), val(o.get('virtualization')), val(o.get('load_generator_shares_instance')), 'See raw tiers: differing limits' if len(unique)>1 else val(runtime.get('topology'))])
        generator_tiers = [t['generator_limits'] for k,t in data['fixed_throughput']['tiers'].items() if k.startswith(v+'/') and t.get('generator_limits')]
        g = generator_tiers[0] if generator_tiers and len({__import__('json').dumps(l,sort_keys=True) for l in generator_tiers}) == 1 else runtime.get('generator_limits') or {}
        generator.append([name, 'Unlimited quota' if g.get('unlimited_cpu_quota') else val(g.get('effective_cpu_quota_cores')) + ' cores', val(g.get('cpuset_cpus_effective')), val(g.get('main_process_cpu_affinity', runtime.get('generator_cpu_affinity'))), 'Unlimited' if g.get('unlimited_memory') else val(g.get('effective_memory_limit_bytes')/1e6 if g.get('effective_memory_limit_bytes') is not None else None) + ' MB'])
    lines += table(['Agent','Instance (observed)','Region / AZ','Logical vCPUs','CPU model','Architecture','Cores/socket / sockets / threads/core','Installed memory','OS','Kernel'], rows)
    lines += table(['Agent','Observed storage','AWS volumes: type / GiB / IOPS / MiB/s','AWS network baseline / maximum','AWS EBS baseline / maximum'], storage)
    lines += ['Bandwidth field units follow [AWS network specifications](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html), [EBS instance specifications](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_EbsOptimizedInfo.html) and [volume configuration](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_Volume.html). GiB = 2³⁰ bytes; MiB = 2²⁰ bytes. Installed memory is observed OS-accessible MemTotal, not the instance SKU’s advertised memory; advertised memory and CPU topology are retained in hardware JSON.', '']
    lines += table(['Agent','Effective CPU quota','CPU set','Effective memory max','memory.high (bytes or max)','Virtualization/container detection','Loadgen shares instance','Execution topology'], limits)
    lines += table(['Agent instance','Generator CPU quota','Generator CPU set','Generator process affinity','Generator memory limit'], generator)
    lines += ['Limits include ancestor cgroups. Unlimited quota does not grant more CPUs than the effective CPU set or host. Agent memory and CPU cover the systemd service and descendants; the colocated generator is measured separately. N/A or differing limits are not assumed equal. Machine comparison allows at most 64 KiB variation in observed OS-accessible MemTotal only when published AWS memory capacities match; all exact observed values remain in raw JSON.', '']
    return lines


def report(data, vendors, cases):
    f = data['fixed_throughput']
    rates = rates_for(data.get('provenance', {}))
    lines = hardware_report(data, vendors)
    lines += ['## Fixed-throughput resource comparisons', '']
    if not f['measured']:
        return lines + ['Not measured in this historical result format. Fixed-rate CPU, average memory, attainment and efficiency are N/A; no extrapolation from best-throughput results.', '']
    lines += ['Each tested tier is an independent measured workload: ' + ' / '.join(f'{r:,}' for r in rates) + ' total input logs/sec across 256 workers. One global scheduler permits at most 5 ms catch-up; missed deadlines and full worker queues are counted. All agents use the same retained NDJSON corpus, one log per HTTP request, 30 seconds of stable service startup, 10 seconds of offered-load warm-up, 60 seconds of measurement, then bounded HTTP drain and 60 seconds of post-load observation. Measurement order is recorded in provenance: ' + str(data.get('provenance', {}).get('fixed_rate', {}).get('measurement_order', 'all best-throughput scenarios, then all fixed-rate scenarios')) + '. The daily workflow runs agents in parallel on separate instances; scenarios and tiers remain sequential. Direct runs use the topology recorded in the hardware table.', '', '**Sustains target:** actual offered rate is within ±2% of target; acknowledged rate is at least 98% of both target and actual offered rate; no unrecovered errors or backpressure; valid duration, resource sampling, service continuity and completed HTTP drain. The standalone generator calibration must pass the same rate criterion and scheduler misses must be ≤2%. This is acknowledged HTTP ingestion, not verified durable delivery or proof of stable agent backlog.', '', '**Measurement scope and units:** CPU 100% means one logical core. Average CPU uses cumulative cgroup CPU deltas over the measurement window. Memory is the whole service cgroup (descendants, page cache and charged kernel memory), in decimal MB = 1,000,000 bytes. Average memory is time-weighted with trapezoidal integration of approximately 1-second samples; peak memory is the maximum sampled value, not an unsampled high-water mark. Generator CPU/RSS and host busy counters remain in data.json and raw samples.', '', '**Efficiency:** logs/sec/core = acknowledged logs/sec ÷ (CPU%/100), higher is better. CPU µs/acknowledged log = (CPU%/100) × 1,000,000 ÷ acknowledged logs/sec, lower is better. Throughput per memory = acknowledged logs/sec ÷ average memory MB, higher is better. These are agent resources only; generator resources are excluded. Lower usage from a tier that does not sustain target is not an equal-throughput win.', '', '**Statuses:** `ok` meets the criterion; `capacity_limited` records rejection/failure or acknowledgement shortfall in this colocated setup; `generator_limited` means standalone calibration, scheduling or inconclusive under-offering prevents isolating agent capacity; `invalid` means broken/missing evidence or service continuity; `missing` means no result; `unsupported` means the suite has no implementation. Target shortfalls (`capacity_limited` or `generator_limited`) are reported as failed attainment; the latter does not prove an agent capacity limit. `skipped_after_shortfall` means a higher tier was deliberately not tested after an earlier measured shortfall, with no extrapolated metrics. Missing and invalid evidence still blocks publication. Reports with target shortfalls explicitly state those failures and any generator uncertainty. Only sustained targets qualify for resource-winner comparisons.', '']
    supported = [t for t in f['tiers'].values() if t['status'] != 'unsupported']
    counts = {s: sum(t['status']==s for t in supported) for s in sorted({t['status'] for t in supported})}
    lines += ['### Measured summary', '', ', '.join(f'{s}: **{n}**' for s,n in counts.items()) + f' across **{len(supported)} supported fixed-rate tiers**. Only valid sustained tiers contribute to comparative aggregates. No agent backlog stability claim is made.', '']
    lines += ['### Highest measured sustained target by scenario', '', 'These are the highest sustained tested tiers, not exact maximum capacities. N/A means no tested tier sustained the criterion (or unsupported), not zero capacity. Higher tiers skipped after a shortfall have no measurements. Old runs that tested every tier retain every measured result.', '']
    attainment = f['scenario_attainment']
    lines += table(['Scenario', 'Agent', 'Highest sustained tested target logs/sec', 'Lowest failed tested target logs/sec', 'Interpretation'],
        [[c, n, val(attainment[f'{v}/{c}']['highest_measured_sustained_target'],0),
          val(attainment[f'{v}/{c}']['lowest_measured_failed_target'],0),
          'Unsupported' if attainment[f'{v}/{c}']['unsupported'] else 'Measured tiers only; see diagnostic status below']
         for c in cases for v,(_,n) in vendors.items()])
    for case in cases:
        for rate in rates:
            rows = [(name, f['tiers'][f'{v}/{case}/{rate}']) for v,(_,name) in vendors.items()]
            lines += [f'### {case} — {rate:,} target logs/sec', '']
            lines += table(['Scenario','Target logs/sec','Agent','Offered logs/sec','Acknowledged logs/sec','Avg CPU %','Avg memory MB','Peak memory MB','Duration sec','Sustains target','Target result / diagnostic'], [[case,f'{rate:,}',n,*[val(t.get(k)) for k in ['offered_logs_per_second','acknowledged_logs_per_second','agent_cpu_percent','agent_avg_memory_mb','agent_peak_memory_mb','duration_seconds']],val(t.get('sustains_target')),('PASS' if t['status']=='ok' else 'FAIL — target not sustained' if t['status'] in ('capacity_limited','generator_limited') else 'NOT TESTED' if t['status']=='skipped_after_shortfall' else t['status']) + ' / ' + t['status']] for n,t in rows])
            lines += table(['Agent','Logs/sec/core ↑','CPU µs/ack log ↓','Logs/sec/avg memory MB ↑','Eligible equal-throughput comparison'], [[n,*[val(t.get(k)) for k in ['logs_per_second_per_core','cpu_microseconds_per_acknowledged_log','logs_per_second_per_mb']], 'Yes' if t.get('comparison_eligible') else 'No'] for n,t in rows])
            lines += table(['Agent','Errors','Backpressure','Scheduler missed','Queue dropped','In-flight at end / after drain','Queued at end','HTTP drain sec','Ack after window','Status / reason'], [[n,*[val(t.get(k),0) for k in ['errors','backpressure','scheduler_missed_logs','worker_queue_dropped_logs']],val(t.get('client_inflight_at_end'),0)+' / '+val(t.get('client_inflight_after_drain'),0),val(t.get('client_queue_at_end'),0),val(t.get('http_drain_seconds')),val(t.get('acknowledged_after_window'),0),t.get('reason',t['status'])] for n,t in rows])
    lines += ['### Comparable aggregate efficiency', '', 'Matching supported scenarios only: **' + ', '.join(f['common_scenarios']) + '**. Each agent must sustain every matching scenario at that target; unknown or differing machine/service configurations exclude cross-agent aggregates. Ratios use sums of acknowledged rates divided by sums of measured cores or average memory; exclusions remain N/A. Different payload/config semantics still limit product-level conclusions.', '']
    lines += table(['Target logs/sec','Agent','Logs/sec/core ↑','CPU µs/ack log ↓','Logs/sec/avg memory MB ↑','Status'], [[f'{r:,}',n,*[val(f['common_scenario_aggregates'][f'{v}/{r}'].get(k)) for k in ['logs_per_second_per_core','cpu_microseconds_per_acknowledged_log','logs_per_second_per_mb']],f['common_scenario_aggregates'][f'{v}/{r}']['status']] for r in rates for v,(_,n) in vendors.items()])
    lines += ['### Fixed-rate reliability and backlog interpretation', '', 'Errors count final failed logical request outcomes, including completion during HTTP drain; backpressure (HTTP 429/503) is a subset of errors, not an additional error count. Offered rate counts logical requests whose full request was written during the measurement window, once even if retried. Acknowledged rate counts successful HTTP responses completed during that window. Post-window acknowledgements are separate. Requests queued but never dispatched, scheduling misses, and worker queue drops are not acknowledgements or HTTP errors.', '', 'Client queue depth and in-flight requests are observed at the end; HTTP drain measures completion of those client requests. Agent backlog before/after and agent drain completion are **N/A (not measured)**. The 60-second post-load observation is not proof that internal buffers or downstream storage drained. Raw records retain all warm-up and measured retry, connection, recovered-request, ambiguous-delivery and generator calibration counters. At-least-once retries may duplicate ingestion; no durable-delivery assertion is made.', '']
    return lines
