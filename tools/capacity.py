"""Bounded Rust rate search, reusing actual fixed-rate evidence (schema 4+)."""
import json
from pathlib import Path
import fixed

LOW_RATES = [1000, 2500, 5000]
HIGH_RATES = [200000, 250000]
OUTCOMES = ('ok', 'no_sustained_rate', 'generator_limited')


def enabled(provenance):
    return provenance.get('schema_version', 1) >= 4


def policy(provenance):
    short = provenance.get('benchmark_profile') == 'short'
    return {'method': 'rust-sustained-rate-search-v1', 'reuses_fixed_tiers': True,
            'low_probes': [] if short else LOW_RATES,
            'high_probes': [] if short else HIGH_RATES,
            'selection': 'highest acknowledged rate among passing measurements',
            'ceiling_logs_per_second': 125000 if short else HIGH_RATES[-1]}


def next_probe(provenance, outcomes):
    """Stop each extra ladder on its first shortfall; never skip a missing probe."""
    if provenance.get('benchmark_profile') == 'short': return None
    rates = fixed.rates_for(provenance)
    if outcomes.get(rates[0]) in fixed.SHORTFALL_STATUSES:
        ladder = LOW_RATES
    elif outcomes.get(rates[-1]) == 'ok':
        ladder = HIGH_RATES
    else:
        return None
    for rate in ladder:
        if rate not in outcomes: return rate
        if outcomes[rate] != 'ok': return None
    return None


def summarize(directory, vendor, case, provenance):
    """Recompute the search and selected tier from raw files, not manifest claims."""
    directory = Path(directory)
    result = {'status': 'missing', 'method': 'rust-sustained-rate-search-v1',
              'reason': 'No completed Rust throughput search', 'trials': [],
              'avg': None, 'peak': None, 'cpu': None, 'mem': None, 'total': None}
    manifest = directory / f'{vendor}_{case}.capacity.json'
    if not manifest.exists(): return result
    try:
        raw = json.loads(manifest.read_text())
        if raw.get('synthetic'): result['synthetic'] = True
        if (raw.get('schema_version') != 1 or raw.get('vendor') != vendor or raw.get('scenario') != case
                or raw.get('complete') is not True or raw.get('policy') != policy(provenance)
                or provenance.get('throughput') != policy(provenance)):
            raise ValueError('Incomplete search, wrong identity or search policy')
        payload = provenance['fixed_rate']['payload_sha256']
        generator = provenance['fixed_rate'].get('generator', {})
        if generator.get('generator') != 'rust' or generator.get('dispatch_mode') != 'workers' or not isinstance(generator.get('version'), str):
            raise ValueError('Missing Rust worker generator provenance')
        outcomes = {}; rates = list(fixed.rates_for(provenance)); extra = []
        shortfall = False
        for rate in rates:
            t = fixed.tier(directory, vendor, case, rate, payload)
            if t['status'] not in fixed.REPORTABLE_STATUSES:
                raise ValueError(f'{rate}: {t["status"]}: {t["reason"]}')
            if shortfall and t['status'] != 'skipped_after_shortfall':
                raise ValueError('Higher fixed tier was measured after a shortfall')
            shortfall = shortfall or t['status'] in fixed.SHORTFALL_STATUSES
            outcomes[rate] = t['status']; result['trials'].append(t)
        while (rate := next_probe(provenance, outcomes)) is not None:
            t = fixed.tier(directory, vendor, case, rate, payload)
            if t['status'] not in fixed.MEASURED_STATUSES:
                raise ValueError(f'Capacity probe {rate}: {t["status"]}: {t["reason"]}')
            extra.append(rate); outcomes[rate] = t['status']; result['trials'].append(t)
        if raw.get('probe_rates') != extra or raw.get('fixed_rates') != rates:
            raise ValueError('Search coverage differs from measured outcomes')
        for scope in ['limits', 'generator_limits']:
            measured = [t for t in result['trials'] if t['status'] in fixed.MEASURED_STATUSES]
            required = {'cpu_max', 'memory_max_bytes', 'cpuset_cpus_effective', 'main_process_cpu_affinity', 'cpu_ancestors_observed', 'memory_ancestors_observed'}
            if any(not isinstance(t.get(scope), dict) or not required <= set(t[scope]) for t in measured):
                raise ValueError(f'Missing {scope} inspection in search')
            if len({json.dumps(t[scope], sort_keys=True) for t in measured}) != 1:
                raise ValueError(f'{scope} changed between fixed tiers and capacity probes')
        # Reject unexplained extra measurements instead of silently omitting evidence.
        for rate in LOW_RATES + HIGH_RATES:
            if rate not in extra and (directory / f'{vendor}_{case}_{rate}.fixed.json').exists():
                raise ValueError(f'Unexpected capacity probe {rate}')
        passed = [t for t in result['trials'] if t['status'] == 'ok']
        failed = [t for t in result['trials'] if t['status'] in fixed.SHORTFALL_STATUSES]
        result.update(probe_rates=extra, highest_sustained_target=max((t['target_logs_per_second'] for t in passed), default=None),
                      lowest_failed_target=min((t['target_logs_per_second'] for t in failed), default=None),
                      ceiling_logs_per_second=policy(provenance)['ceiling_logs_per_second'],
                      ceiling_reached=any(t['target_logs_per_second']==policy(provenance)['ceiling_logs_per_second'] for t in passed),
                      generator_uncertainty=any(t['status']=='generator_limited' for t in failed),
                      agent_maximum_established=False)
        if passed:
            best = max(passed, key=lambda t: (t['acknowledged_logs_per_second'], t['target_logs_per_second']))
            result.update(status='ok', reason='Highest acknowledged rate among passing measured tiers; not a maximum-capacity claim',
                          selected_target=best['target_logs_per_second'], avg=best['acknowledged_logs_per_second'],
                          total=best['acknowledged_logs'], cpu=best['agent_cpu_percent'],
                          mem=best['agent_peak_memory_mb']*1e6/2**20,
                          average_memory_mb=best['agent_avg_memory_mb'], peak_memory_mb=best['agent_peak_memory_mb'],
                          duration_seconds=best['duration_seconds'], measurement=best)
        else:
            result.update(status='generator_limited' if result['generator_uncertainty'] else 'no_sustained_rate',
                          reason='No tested tier met the sustained-rate criterion; no zero-capacity claim')
    except (ValueError, KeyError, TypeError, AttributeError, OSError, ArithmeticError) as error:
        result.update(status='invalid', reason=str(error))
    return result


def assets(directory, vendor, case, entry):
    directory = Path(directory)
    files = [directory/f'{vendor}_{case}.capacity.json']
    for rate in entry.get('probe_rates', []):
        files.extend([directory/f'{vendor}_{case}_{rate}.fixed.json', directory/f'{vendor}_{rate}.calibration.json'])
    return files


def detail_report(data, vendors, cases):
    from fixed_report import table, val
    lines = ['## Rust sustained-throughput search', '',
             'The fixed-rate and throughput tests share the same Rust generator, immutable corpus, 256 workers, '
             '10-second warm-up, 60-second measurement, 60-second post-load observation and retry policy. '
             'Fixed tiers are measured once and reused. Full searches probe 1k/2.5k/5k when 10k fails, '
             'or 200k/250k when 125k passes, stopping each ladder on its first shortfall. '
             'The highest passing acknowledged rate is reported; no maximum agent capacity or stable backlog is claimed. '
             'CPU 100% is one logical core; memory is whole-service cgroup usage in decimal MB. '
             'No sampled peak-throughput metric is fabricated. HTTP acknowledgments do not verify durable delivery.', '']
    for case in cases:
        lines += [f'### {case.title()} — search evidence', '']
        rows = []
        for vendor, (_, name) in vendors.items():
            entry = data['scenarios'][f'{vendor}/{case}']
            for t in sorted(entry.get('trials', []), key=lambda t: -t['target_logs_per_second']):
                rows.append([name, val(t['target_logs_per_second'],0), t['status'], val(t.get('offered_logs_per_second'),1),
                             val(t.get('acknowledged_logs_per_second'),1), val(t.get('agent_cpu_percent'),1),
                             val(t.get('agent_avg_memory_mb'),1), val(t.get('agent_peak_memory_mb'),1),
                             val(t.get('errors'),0), val(t.get('backpressure'),0), val(t.get('retry_attempts'),0), val(t.get('ambiguous_deliveries'),0)])
        lines += table(['Agent','Target logs/sec','Status','Offered logs/sec','Acknowledged logs/sec','Avg CPU %','Avg memory MB','Peak memory MB','Final errors','Backpressure','Retries','Ambiguous deliveries'], rows)
    return lines
