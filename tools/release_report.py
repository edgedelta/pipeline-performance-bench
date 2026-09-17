"""Reader-facing release summary; full diagnostics remain in report/data assets."""
import math
import re
import capacity

from fixed import rates_for
from fixed_report import table, val
from summarize import VENDORS, CASES
from report_disclosure import disclosure


def leaders(entries, metric):
    """All ties at the highest positive, finite, valid measurement (before rounding)."""
    eligible = {key: t[metric] for key, t in entries.items()
                if t.get('status') == 'ok' and isinstance(t.get(metric), (int, float))
                and math.isfinite(t[metric]) and t[metric] > 0}
    best = max(eligible.values(), default=None)
    return {key for key, value in eligible.items() if value == best}


def bold(value):
    return f'**{value}**'


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
    return table(['Setting', 'Value — shared unless stated otherwise'], [[field, shared(values)] for field,values in sorted(rows.items(), key=lambda item: item[0].casefold())])


def highest_target(tiers, vendor, case='pass-through'):
    passed = [t['target_logs_per_second'] for key, t in tiers.items() if key.startswith(f'{vendor}/{case}/') and t['status'] == 'ok']
    return max(passed) if passed else -1


def throughput_order(data):
    def key(item):
        vendor, (_, name) = item
        t = data['scenarios'].get(f'{vendor}/pass-through', {})
        group = 0 if t.get('status') == 'ok' else 1 if t.get('status') == 'errors' else 2
        return group, -(t.get('avg') if t.get('avg') is not None else -1), name.casefold()
    return sorted(VENDORS.items(), key=key)


def fixed_order(tiers, case, rate):
    def key(item):
        vendor, (_, name) = item
        t = tiers[f'{vendor}/{case}/{rate}']
        passed = t['status'] == 'ok'
        group = 0 if passed else 1 if t['status'] in ('capacity_limited', 'generator_limited') else 2
        metric = t.get('logs_per_second_per_core' if passed else 'acknowledged_logs_per_second')
        return group, -(metric if metric is not None else -1), name.casefold()
    return sorted(VENDORS.items(), key=key)


def throughput_resources(data):
    """Resources from the selected passing window, never from another target."""
    lines = []
    for case in CASES:
        lines += [f'### {case.title()} — best sustained throughput', '']
        entries = {v: data['scenarios'].get(f'{v}/{case}', {}) for v in VENDORS}
        winners = leaders(entries, 'avg')
        order = sorted(VENDORS, key=lambda v: (entries[v].get('status') != 'ok',
                       -(entries[v].get('avg') or 0) if entries[v].get('status') == 'ok' else 0,
                       VENDORS[v][1].casefold()))
        rows = []
        for vendor in order:
            t = entries[vendor]; name = VENDORS[vendor][1]
            if t.get('status') == 'ok':
                rate = val(t.get('avg'), 0)
                if vendor in winners: name = '🏆 ' + bold(name); rate = bold(rate)
                if t.get('ceiling_reached'): rate += ' †'
                if t.get('generator_uncertainty'): rate += ' ‡'
                measured = t.get('measurement', {})
                rows.append([name, rate, val(t.get('cpu'), 1), val(t.get('average_memory_mb'), 1),
                             val(t.get('peak_memory_mb'), 1), val(measured.get('logs_per_second_per_core'), 0),
                             val(measured.get('logs_per_second_per_mb'), 0)])
            else:
                status = {'no_sustained_rate': 'No passing tier', 'generator_limited': 'No passing tier ‡',
                          'unsupported': 'Unsupported', 'missing': 'Missing', 'invalid': 'Invalid'}.get(t.get('status'), 'N/A')
                rows.append([name, status, *(['N/A'] * 5)])
        lines += table(['Agent', 'Acknowledged logs/sec ↑', 'Avg CPU %', 'Avg memory MB',
                        'Peak memory MB', 'Logs/sec/core ↑', 'Logs/sec/MB ↑'], rows)
    return lines


def render(data, run_url, synthetic=False):
    rust_search = capacity.enabled(data.get('provenance', {}))
    f = data['fixed_throughput']
    rates = rates_for(data.get('provenance', {}))
    tiers = f['tiers']
    lines = []
    if synthetic:
        lines += ['> **SYNTHETIC FIXTURE — NOT REAL MEASUREMENTS. DO NOT PUBLISH.**', '']
    lines += [disclosure(data.get('provenance')).rstrip(), '']
    lines += [f"**Benchmark date:** {data.get('date', 'N/A')} · [Workflow run]({run_url})", '']
    if f['measured']:
        counts = {s: sum(t['status'] == s for t in tiers.values()) for s in ['ok','capacity_limited','generator_limited','skipped_after_shortfall','invalid','missing']}
        lines += [f"**Fixed-rate results: {counts['ok']} passed · {counts['capacity_limited']+counts['generator_limited']} failed to sustain target · {counts['skipped_after_shortfall']} higher tiers not tested.**", '']
        if counts['generator_limited']:
            lines += [f"{counts['generator_limited']} failed tests have source/bottleneck uncertainty; they do not establish an agent-only capacity limit.", '']
        if counts['invalid'] or counts['missing']:
            lines += [f"**Incomplete evidence: {counts['invalid']} invalid and {counts['missing']} missing tiers.**", '']
    generator = data.get('provenance', {}).get('fixed_rate', {}).get('generator')
    if generator:
        usage = 'for throughput, fixed rates and calibration.' if rust_search else 'for fixed rates and calibration; Go for best-tested throughput.'
        lines += [f"**Load generators:** Rust workers ({val(generator.get('version'))}, 256 workers) {usage}", '']
    legend = '🏆 **Bold values** mark the highest valid result in each scenario, including ties.'
    if f['measured']:
        legend += ' In fixed-rate tables, 🔹 **bold rows** mark the highest observed logs/sec/core among passing agents at that scenario and target; a sole passing agent is highlighted too.'
    methodology = ('Acknowledged HTTP ingestion, in logs/sec. Each value is the highest acknowledged rate from a passing Rust rate-search tier. '
                   'The search reuses the fixed-rate measurements with identical corpus, workers, measurement windows and delivery policy. '
                   'Full runs also probe 1k/2.5k/5k if 10k fails, or 200k/250k if 125k passes, stopping each extra ladder on its first shortfall. '
                   'These are measured sustainable rates, not proven maximum agent capacities; durable downstream delivery and backlog stability are not verified. '
                   'Each scenario is sorted by acknowledged throughput, highest first; unavailable results follow valid results.') if rust_search else 'Acknowledged HTTP ingestion, in logs/sec. Each value is the best of the three measured worker settings; durable downstream delivery is not verified. Rows are sorted by pass-through throughput, highest first; flagged or unavailable pass-through results follow valid results.'
    lines += ['## Best-tested throughput', '', legend, '', methodology, '']
    if rust_search:
        lines += ['† Passed the highest tested ceiling; higher capacity was not tested. ‡ A higher-rate test had source/bottleneck uncertainty, so an agent-only limit cannot be determined. No passing tier does not mean zero capacity.', '']
        lines += ['Throughput is actual acknowledged logs divided by measured seconds, rounded to the nearest log/sec—not the configured target. CPU, memory and efficiency come from that same selected window. CPU 100% means one logical core; memory is whole-service cgroup usage in MB = 1,000,000 bytes (peak is the highest sampled value). These resource values are measured at different throughputs; use the fixed-rate tables for equal-throughput comparisons.', '']
    throughput_leaders = {case: leaders({v: data['scenarios'].get(f'{v}/{case}', {}) for v in VENDORS}, 'avg') for case in CASES}
    rows = []
    for vendor, (_, name) in throughput_order(data):
        cells = []
        for case in CASES:
            t = data['scenarios'].get(f'{vendor}/{case}', {})
            status = t.get('status', 'missing')
            cells.append(val(t.get('avg'),0) + (' †' if status == 'errors' else '') if status in ('ok','errors') else 'Unsupported' if status == 'unsupported' else status.title())
            if vendor in throughput_leaders[case]: cells[-1] = bold(cells[-1])
            if rust_search:
                if status == 'ok':
                    if t.get('ceiling_reached'): cells[-1] += ' †'
                    if t.get('generator_uncertainty'): cells[-1] += ' ‡'
                else:
                    cells[-1] = {'no_sustained_rate': 'No passing tier', 'generator_limited': 'No passing tier ‡'}.get(status, cells[-1])
        rows.append(['🏆 ' + bold(name) if any(vendor in winners for winners in throughput_leaders.values()) else name,*cells])
    lines += throughput_resources(data) if rust_search else table(['Agent','Pass-through','Filter','Mask','Lookup'],rows)
    if any(t.get('status') == 'errors' for t in data['scenarios'].values()):
        lines += ['† Completed with request errors; excluded from rankings. The detailed report retains the error counts.', '']
    if f['measured']:
        lines += ['## Highest sustained fixed-rate target', '', 'Logs/sec at the highest tested tier that passed. “None” means no tested tier passed, not zero capacity. Higher skipped tiers have no inferred result. Rows are sorted by pass-through target, highest first; ties use filter, mask, then lookup targets, followed by agent name.', '']
        target_leaders = {case: leaders({v: {'status': 'ok', 'target': highest_target(tiers, v, case)} for v in VENDORS}, 'target') for case in CASES}
        rows = []
        for vendor, (_, name) in sorted(VENDORS.items(), key=lambda item: tuple(-highest_target(tiers, item[0], case) for case in CASES) + (item[1][1].casefold(),)):
            cells = []
            for case in CASES:
                selected = [tiers[f'{vendor}/{case}/{rate}'] for rate in rates]
                passed = [t['target_logs_per_second'] for t in selected if t['status']=='ok']
                cells.append('Unsupported' if all(t['status']=='unsupported' for t in selected) else val(max(passed),0) if passed else 'None' if any(t['status'] in ('capacity_limited','generator_limited') for t in selected) else 'N/A')
                if vendor in target_leaders[case]: cells[-1] = bold(cells[-1])
            rows.append(['🏆 ' + bold(name) if any(vendor in winners for winners in target_leaders.values()) else name,*cells])
        lines += table(['Agent','Pass-through','Filter','Mask','Lookup'],rows)
        if rust_search:
            lines += ['This target overview covers the standard fixed-rate resource tiers only. Additional throughput-search probes contribute to best-tested throughput above and are retained in the detailed report and raw assets.', '']
    lines += ['## Hardware and test setup', ''] + hardware(data)
    lines += [f"**Execution:** {data.get('provenance', {}).get('execution_mode', 'N/A')}. Hardware settings are shown once; exact per-instance readings remain in the assets. AWS bandwidth values are published limits, not measured bandwidth.", '']
    if f['measured']:
        lines += ['## CPU and memory at fixed rates', '', 'Each measured tier uses the same fixed input corpus, 10-second warm-up and 60-second measurement window. Pass requires offered rate within ±2% of target, acknowledged rate ≥98% of target and offered rate, and successful source, delivery and measurement checks.', '', 'CPU **100% = one logical core**. Memory is average whole-service cgroup usage in **MB = 1,000,000 bytes**. Logs/sec/core = acknowledged rate ÷ (CPU%/100); logs/sec/MB = acknowledged rate ÷ average memory. Higher efficiency values are better; failed tiers are not equal-throughput wins. Targets are shown highest first: ' + ', '.join(f'{r:,}' for r in reversed(rates)) + ' logs/sec. Within each target, passing rows come first, sorted by logs/sec/core descending. Failed rows follow, sorted by achieved throughput; ties use agent name.', '']
        if not f.get('matching_environment'):
            lines += ['Fixed-rate highlights identify leading observed values, not a verified equal-resource winner: equal machine/process limits could not be fully verified. Failed tiers are never highlighted.', '']
        for case in CASES:
            lines += [f'### {case.title()} — measured CPU, memory and efficiency', '']
            rows = []
            for rate in reversed(rates):
                winners = leaders({v: tiers[f'{v}/{case}/{rate}'] for v in VENDORS}, 'logs_per_second_per_core')
                for vendor, (_,name) in fixed_order(tiers, case, rate):
                    t = tiers[f'{vendor}/{case}/{rate}']; status = t['status']
                    if status == 'unsupported': continue
                    result = {'ok':'Pass','capacity_limited':'Fail','generator_limited':'Fail*','skipped_after_shortfall':'Not tested','invalid':'Invalid','missing':'Missing'}.get(status,status)
                    if status == 'skipped_after_shortfall':
                        continue  # Group unmeasured higher rates once per agent below.
                    row = [f'{rate:,}',name,*[val(t.get(k),1 if k=='agent_cpu_percent' else 0) for k in ['acknowledged_logs_per_second','agent_cpu_percent','agent_avg_memory_mb','logs_per_second_per_core','logs_per_second_per_mb']],result]
                    if vendor in winners:
                        row = [bold(cell) for cell in row]
                        row[1] = '🔹 ' + row[1]
                    rows.append(row)
            lines += table(['Target logs/sec','Agent','Achieved logs/sec','Avg CPU %','Avg memory MB','Logs/sec/core ↑','Logs/sec/MB ↑','Result'],rows)
            skipped = []
            for vendor, (_,name) in sorted(VENDORS.items(), key=lambda item: item[1][1].casefold()):
                skipped_rates = [f'{rate:,}' for rate in reversed(rates) if tiers[f'{vendor}/{case}/{rate}']['status']=='skipped_after_shortfall']
                if skipped_rates: skipped.append(f'{name}: {", ".join(skipped_rates)}')
            if skipped: lines += ['**Not tested after a lower target failed:** ' + '; '.join(skipped) + ' logs/sec.', '']
        lines += ['`Fail*`: source/bottleneck uncertainty. Unsupported: OTel lookup and Fluent Bit masking. Pipeline implementations differ; these measurements are not proof of identical processing semantics.', '']
    else:
        lines += ['Fixed-rate CPU and memory comparisons were not measured in this historical result format.', '']
    lines += ['## Tested agent versions and source', '', 'Agents are listed alphabetically.', '']
    versions = []
    for key, name in sorted(VENDORS.values(), key=lambda item: item[1].casefold()):
        version = data['versions'].get(key, 'N/A')
        if version.startswith('Agent version: '): version = version.split(',',1)[0].removeprefix('Agent version: ')
        versions.append([name,val(version)])
    lines += table(['Agent','Version'],versions)
    lines += [f"Benchmark source: `{data.get('provenance', {}).get('benchmark_commit', 'N/A')}`", '']
    match = re.fullmatch(r'https://github.com/([^/]+/[^/]+)/actions/runs/\d+',run_url)
    if match and re.fullmatch(r'\d{8}_\d{6}',data['runId']):
        base = f"https://github.com/{match[1]}/releases/download/{data['runId'].replace('_','-')}"
        lines += [f'[Detailed report]({base}/report.md) · [Structured data]({base}/data.json) · [Checksums]({base}/SHA256SUMS)', '']
    else:
        lines += ['Detailed measurements and diagnostics: `report.md`, `data.json` and raw release assets.', '']
    return '\n'.join(lines)
