"""Reader-facing release summary; full diagnostics remain in report/data assets."""
import re

from fixed import RATES
from fixed_report import table, val
from summarize import VENDORS, CASES


def shared(values):
    """Deduplicate identical fields without hiding differences or missing evidence."""
    groups = {}
    for name, value in values:
        groups.setdefault(value, []).append(name)
    if len(groups) == 1:
        return next(iter(groups))
    return '; '.join(f'{", ".join(names)}: {value}' for value, names in groups.items())


def hardware(data):
    rows = {}
    for vendor, (_, name) in VENDORS.items():
        h = data['hardware'].get(vendor, {})
        o = h.get('runtime', {}).get('observed', {})
        p = h.get('published', {})
        ram = p.get('memory_mib')
        observed_ram = o.get('installed_memory_bytes')
        volumes = p.get('volumes') or []
        cards = (p.get('network') or {}).get('cards') or []
        ebs = p.get('ebs') or {}
        fields = {
            'AWS instance / location': f"{val(o.get('instance_type'))} · {val(o.get('region'))} / {val(o.get('availability_zone'))}",
            'CPU': f"{val(o.get('logical_cpus'),0)} vCPUs · {val(o.get('cpu_model'))} · {val(o.get('architecture'))}; {val(o.get('cores_per_socket'),0)} cores/socket × {val(o.get('sockets'),0)} sockets × {val(o.get('threads_per_core'),0)} threads/core",
            'Memory': f"{val(ram/1024 if ram else None,0)} GiB (AWS); ~{val(observed_ram/2**30 if observed_ram else None)} GiB OS-accessible",
            'OS / kernel': f"{val(o.get('os'))} / {val(o.get('kernel'))}",
            'Storage (AWS)': '; '.join(f"{val(v.get('VolumeType'))}, {val(v.get('Size'),0)} GiB, {val(v.get('Iops'),0)} IOPS, {val(v.get('Throughput'),0)} MiB/s" for v in volumes) or 'N/A',
            'Network baseline / maximum (AWS)': '; '.join(f"{val(c.get('BaselineBandwidthInGbps'))} / {val(c.get('PeakBandwidthInGbps'))} Gbps" for c in cards) or 'N/A',
            'EBS bandwidth baseline / maximum (AWS)': f"{val(ebs.get('BaselineBandwidthInMbps'),0)} / {val(ebs.get('MaximumBandwidthInMbps'),0)} Mbps",
            'Load generator shares agent instance': val(o.get('load_generator_shares_instance')),
        }
        limits = [t.get('limits') for k,t in data['fixed_throughput']['tiers'].items() if k.startswith(vendor+'/') and t.get('limits')]
        fields['Agent CPU quota / memory limit'] = shared([(str(i),
            ('Unlimited' if l.get('unlimited_cpu_quota') else val(l.get('effective_cpu_quota_cores')) + ' cores') + ' / ' +
            ('Unlimited' if l.get('unlimited_memory') else val(l.get('effective_memory_limit_bytes')/1e6 if l.get('effective_memory_limit_bytes') is not None else None) + ' MB'))
            for i,l in enumerate(limits)]) if limits else 'N/A'
        for field, value in fields.items():
            rows.setdefault(field, []).append((name, value))
    return table(['Setting', 'Value — shared unless stated otherwise'], [[field, shared(values)] for field,values in rows.items()])


def render(data, run_url, synthetic=False):
    f = data['fixed_throughput']
    tiers = f['tiers']
    lines = []
    if synthetic:
        lines += ['> **SYNTHETIC FIXTURE — NOT REAL MEASUREMENTS. DO NOT PUBLISH.**', '']
    lines += [f"**Benchmark date:** {data.get('date', 'N/A')} · [Workflow run]({run_url})", '']
    if f['measured']:
        counts = {s: sum(t['status'] == s for t in tiers.values()) for s in ['ok','capacity_limited','generator_limited','skipped_after_shortfall','invalid','missing']}
        lines += [f"**Fixed-rate results: {counts['ok']} passed · {counts['capacity_limited']+counts['generator_limited']} failed to sustain target · {counts['skipped_after_shortfall']} higher tiers not tested.**", '']
        if counts['generator_limited']:
            lines += [f"{counts['generator_limited']} failed tests have source/bottleneck uncertainty; they do not establish an agent-only capacity limit.", '']
        if counts['invalid'] or counts['missing']:
            lines += [f"**Incomplete evidence: {counts['invalid']} invalid and {counts['missing']} missing tiers.**", '']
    lines += ['## Best-tested throughput', '', 'Acknowledged HTTP ingestion, in logs/sec. Each value is the best of the three measured worker settings; durable downstream delivery is not verified.', '']
    rows = []
    for vendor, (_, name) in VENDORS.items():
        cells = []
        for case in CASES:
            t = data['scenarios'].get(f'{vendor}/{case}', {})
            status = t.get('status', 'missing')
            cells.append(val(t.get('avg'),0) + (' †' if status == 'errors' else '') if status in ('ok','errors') else 'Unsupported' if status == 'unsupported' else status.title())
        rows.append([name,*cells])
    lines += table(['Agent','Pass-through','Filter','Mask','Lookup'],rows)
    if any(t.get('status') == 'errors' for t in data['scenarios'].values()):
        lines += ['† Completed with request errors; excluded from rankings. The detailed report retains the error counts.', '']
    if f['measured']:
        lines += ['## Highest sustained fixed-rate target', '', 'Logs/sec at the highest tested tier that passed. “None” means no tested tier passed, not zero capacity. Higher skipped tiers have no inferred result.', '']
        rows = []
        for vendor, (_, name) in VENDORS.items():
            cells = []
            for case in CASES:
                selected = [tiers[f'{vendor}/{case}/{rate}'] for rate in RATES]
                passed = [t['target_logs_per_second'] for t in selected if t['status']=='ok']
                cells.append('Unsupported' if all(t['status']=='unsupported' for t in selected) else val(max(passed),0) if passed else 'None' if any(t['status'] in ('capacity_limited','generator_limited') for t in selected) else 'N/A')
            rows.append([name,*cells])
        lines += table(['Agent','Pass-through','Filter','Mask','Lookup'],rows)
    lines += ['## Hardware and test setup', ''] + hardware(data)
    lines += [f"**Execution:** {data.get('provenance', {}).get('execution_mode', 'N/A')}. Hardware settings are shown once; exact per-instance readings remain in the assets. AWS bandwidth values are published limits, not measured bandwidth.", '']
    if f['measured']:
        lines += ['## CPU and memory at fixed rates', '', 'Each measured tier uses the same fixed input corpus, 10-second warm-up and 60-second measurement window. Pass requires offered rate within ±2% of target, acknowledged rate ≥98% of target and offered rate, and successful source, delivery and measurement checks.', '', 'CPU **100% = one logical core**. Memory is average whole-service cgroup usage in **MB = 1,000,000 bytes**. Logs/sec/core = acknowledged rate ÷ (CPU%/100); logs/sec/MB = acknowledged rate ÷ average memory. Higher efficiency values are better; failed tiers are not equal-throughput wins.', '']
        if not f.get('matching_environment'):
            lines += ['Resource rankings are not assigned because equal machine/process limits could not be fully verified. Measured values are shown below.', '']
        for case in CASES:
            lines += ['<details>', f'<summary>{case.title()} — measured CPU, memory and efficiency</summary>', '']
            rows = []
            for rate in RATES:
                for vendor, (_,name) in VENDORS.items():
                    t = tiers[f'{vendor}/{case}/{rate}']; status = t['status']
                    if status == 'unsupported': continue
                    result = {'ok':'Pass','capacity_limited':'Fail','generator_limited':'Fail*','skipped_after_shortfall':'Not tested','invalid':'Invalid','missing':'Missing'}.get(status,status)
                    if status == 'skipped_after_shortfall':
                        continue  # Group unmeasured higher rates once per agent below.
                    rows.append([f'{rate:,}',name,*[val(t.get(k),1 if k=='agent_cpu_percent' else 0) for k in ['acknowledged_logs_per_second','agent_cpu_percent','agent_avg_memory_mb','logs_per_second_per_core','logs_per_second_per_mb']],result])
            lines += table(['Target logs/sec','Agent','Achieved logs/sec','Avg CPU %','Avg memory MB','Logs/sec/core ↑','Logs/sec/MB ↑','Result'],rows)
            skipped = []
            for vendor, (_,name) in VENDORS.items():
                rates = [f'{rate:,}' for rate in RATES if tiers[f'{vendor}/{case}/{rate}']['status']=='skipped_after_shortfall']
                if rates: skipped.append(f'{name}: {", ".join(rates)}')
            if skipped: lines += ['**Not tested after a lower target failed:** ' + '; '.join(skipped) + ' logs/sec.', '']
            lines += ['</details>', '']
        lines += ['`Fail*`: source/bottleneck uncertainty. Unsupported: OTel lookup and Fluent Bit masking. Pipeline implementations differ; these measurements are not proof of identical processing semantics.', '']
    else:
        lines += ['Fixed-rate CPU and memory comparisons were not measured in this historical result format.', '']
    lines += ['<details>', '<summary>Tested agent versions and source</summary>', '']
    versions = []
    for key, name in VENDORS.values():
        version = data['versions'].get(key, 'N/A')
        if version.startswith('Agent version: '): version = version.split(',',1)[0].removeprefix('Agent version: ')
        versions.append([name,val(version)])
    lines += table(['Agent','Version'],versions)
    lines += [f"Benchmark source: `{data.get('provenance', {}).get('benchmark_commit', 'N/A')}`", '', '</details>', '']
    match = re.fullmatch(r'https://github.com/([^/]+/[^/]+)/actions/runs/\d+',run_url)
    if match and re.fullmatch(r'\d{8}_\d{6}',data['runId']):
        base = f"https://github.com/{match[1]}/releases/download/{data['runId'].replace('_','-')}"
        lines += [f'[Detailed report]({base}/report.md) · [Structured data]({base}/data.json) · [Checksums]({base}/SHA256SUMS)', '']
    else:
        lines += ['Detailed measurements and diagnostics: `report.md`, `data.json` and raw release assets.', '']
    return '\n'.join(lines)
