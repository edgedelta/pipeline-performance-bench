"""Measured fixed-rate metrics. Missing evidence stays missing; no extrapolation."""
import hashlib
import json
import math
from pathlib import Path

LEGACY_RATES = [10000, 25000, 50000, 75000]
RATES = [*LEGACY_RATES, 125000]


def rates_for(provenance):
    """Schema 3 adds 125k; older suites retain their original coverage contract."""
    return RATES if provenance.get("schema_version", 1) >= 3 else LEGACY_RATES

TOLERANCE = .02
MEASURED_STATUSES = ("ok", "capacity_limited", "generator_limited")
SHORTFALL_STATUSES = ("capacity_limited", "generator_limited")
REPORTABLE_STATUSES = (*MEASURED_STATUSES, "skipped_after_shortfall")
COUNTERS = ['scheduled_logs', 'dispatched_logs', 'offered_logs', 'acknowledged_logs', 'acknowledged_after_window', 'errors', 'backpressure', 'connection_errors', 'retry_attempts', 'recovered_requests', 'ambiguous_deliveries', 'scheduler_missed_logs', 'worker_queue_dropped_logs', 'expired_before_dispatch_logs', 'client_inflight_at_end', 'client_inflight_after_drain', 'client_queue_at_end']


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def resources(samples, duration, require_agent=True):
    if len(samples) < 2: raise ValueError('missing resource samples')
    times = [s.get('elapsed_seconds') for s in samples]
    if not all(number(t) for t in times) or times[0] > .1 or abs(times[-1] - duration) > .1 or any(b <= a or b-a > 2.5 for a, b in zip(times, times[1:])):
        raise ValueError('incomplete resource sampling window')
    result = {}
    for prefix, cpu, memory in [('agent', 'agent_cpu_usage_usec', 'agent_memory_bytes'), ('generator', 'generator_cpu_usage_usec', 'generator_rss_bytes')]:
        cpus = [s.get(cpu) for s in samples]; mem = [s.get(memory) for s in samples]
        valid_cpu = all(number(v) for v in cpus) and all(b >= a for a, b in zip(cpus, cpus[1:]))
        valid_mem = all(number(v) for v in mem)
        if prefix == 'agent' and require_agent and not (valid_cpu and valid_mem):
            raise ValueError('missing/reset agent CPU or memory counters')
        result[prefix + '_cpu_percent'] = (cpus[-1]-cpus[0]) / (times[-1]-times[0]) / 10000 if valid_cpu else None
        result[prefix + '_avg_memory_mb'] = sum((a+b)/2*(y-x) for a,b,x,y in zip(mem, mem[1:], times, times[1:])) / (times[-1]-times[0]) / 1e6 if valid_mem else None
        result[prefix + '_peak_memory_mb'] = max(mem) / 1e6 if valid_mem else None
    busy = [s.get('host_busy_ticks') for s in samples]; total = [s.get('host_total_ticks') for s in samples]
    result['host_busy_percent'] = 100*(busy[-1]-busy[0])/(total[-1]-total[0]) if all(number(v) for v in busy+total) and total[-1] > total[0] and 0 <= busy[-1]-busy[0] <= total[-1]-total[0] else None
    return result


def phase(raw, seconds, require_agent=True):
    p = raw['measurement']; duration = p.get('duration_seconds')
    if not number(duration) or not seconds*(1-TOLERANCE) <= duration <= seconds*(1+TOLERANCE) or p.get('canceled') is not False:
        raise ValueError('canceled or incorrect measurement duration')
    if any(not isinstance(p.get(k), int) or isinstance(p[k], bool) or p[k] < 0 for k in COUNTERS):
        raise ValueError('missing/invalid delivery accounting')
    if not number(p.get('http_drain_seconds')) or p['http_drain_seconds'] > 31 or p['client_inflight_after_drain']:
        raise ValueError('incomplete HTTP drain')
    if p['acknowledged_logs'] > p['offered_logs'] or p['offered_logs'] > p['dispatched_logs'] or p['dispatched_logs'] + p['scheduler_missed_logs'] + p['worker_queue_dropped_logs'] + p['expired_before_dispatch_logs'] != p['scheduled_logs']:
        raise ValueError('inconsistent offered/scheduled accounting')
    if p['acknowledged_logs'] + p['acknowledged_after_window'] + p['errors'] != p['dispatched_logs']:
        raise ValueError('incomplete request outcomes')
    if p['recovered_requests'] > p['retry_attempts'] or p['ambiguous_deliveries'] > p['connection_errors'] or p['retry_attempts'] > 2*p['dispatched_logs'] or p['recovered_requests'] > p['acknowledged_logs'] + p['acknowledged_after_window']:
        raise ValueError('inconsistent retry accounting')
    statuses = p.get('http_status_counts')
    if not isinstance(statuses, dict) or any(not str(k).isdigit() or not 100 <= int(k) <= 599 or not isinstance(v, int) or v < 0 for k,v in statuses.items()) or sum(statuses.values()) > p['dispatched_logs']:
        raise ValueError('invalid/missing HTTP status accounting')
    if p['backpressure'] > p['errors']: raise ValueError('backpressure must be a subset of final errors')
    metrics = resources(p.get('resource_samples', []), duration, require_agent)
    metrics.update({k: p[k] for k in COUNTERS})
    metrics.update(http_status_counts=statuses, duration_seconds=duration, offered_logs_per_second=p['offered_logs']/duration, acknowledged_logs_per_second=p['acknowledged_logs']/duration, http_drain_seconds=p['http_drain_seconds'])
    cores = (metrics['agent_cpu_percent'] or 0)/100
    ack = metrics['acknowledged_logs_per_second']; mem = metrics['agent_avg_memory_mb']
    metrics.update(logs_per_second_per_core=ack/cores if cores > 0 else None, cpu_microseconds_per_acknowledged_log=cores*1e6/ack if ack > 0 and metrics['agent_cpu_percent'] is not None else None, logs_per_second_per_mb=ack/mem if mem and mem > 0 else None)
    return metrics


def policy(raw, rate, payload, calibration=False, generator=None):
    if generator is not None:
        expected_generator = {"generator": "rust", "dispatch_mode": "workers", "generator_version": generator["version"].split()[-1]}
        if any(raw.get(k) != v for k, v in expected_generator.items()):
            raise ValueError("fixed-rate generator differs from recorded Rust worker build")
    expected = {'schema_version': 2, 'target_logs_per_second': rate, 'workers': 256, 'payload_sha256': payload, 'warmup_seconds': 2 if calibration else 10, 'configured_measurement_seconds': 10 if calibration else 60, 'request_timeout_seconds': 30, 'max_retries': 2, 'retry_ambiguous': True, 'calibration': calibration}
    if any(raw.get(k) != v for k,v in expected.items()): raise ValueError('inconsistent workload or delivery policy')
    if raw['measurement'].get('scheduled_logs') != rate*expected['configured_measurement_seconds']: raise ValueError('incorrect scheduled target')
    warm = dict(raw, measurement=raw.get('warmup', {}))
    phase(warm, expected['warmup_seconds'], require_agent=not calibration)


def attainment(m, rate):
    return abs(m['offered_logs_per_second']/rate-1) <= TOLERANCE and m['acknowledged_logs_per_second'] >= rate*(1-TOLERANCE) and m['acknowledged_logs_per_second'] >= m['offered_logs_per_second']*(1-TOLERANCE) and not (m['errors'] or m['backpressure'])


def tier(directory, vendor, case, rate, payload):
    path = directory / f'{vendor}_{case}_{rate}.fixed.json'
    result = {'target_logs_per_second': rate, 'status': 'missing', 'sustains_target': None, 'reason': 'No fixed-rate measurement recorded', 'agent_backlog_stability': 'not measured', 'agent_backlog_before': None, 'agent_backlog_after': None}
    if not path.exists(): return result
    try:
        raw = json.loads(path.read_text())
        if raw.get('synthetic'): result['synthetic'] = True
        if raw.get('status') == 'skipped_after_shortfall':
            trigger = raw.get('trigger_target_logs_per_second')
            if (raw.get('schema_version') != 2 or raw.get('vendor') != vendor or raw.get('scenario') != case
                    or raw.get('target_logs_per_second') != rate or raw.get('complete') is not True
                    or raw.get('payload_sha256') != payload or trigger not in RATES or trigger >= rate
                    or 'loadgen' in raw):
                raise ValueError('invalid shortfall skip record')
            evidence = tier(directory, vendor, case, trigger, payload)
            if evidence['status'] not in SHORTFALL_STATUSES:
                raise ValueError('skip requires an earlier measured target shortfall')
            if any(tier(directory, vendor, case, lower, payload)['status'] != 'ok' for lower in RATES if lower < trigger):
                raise ValueError('skip must reference the first measured shortfall')
            result.update(status='skipped_after_shortfall', sustains_target=None,
                          trigger_target_logs_per_second=trigger,
                          reason=f'Not tested after {trigger:,} logs/sec target shortfall ({evidence["status"]}); no higher-rate capacity claim')
            return result
        if raw.get('schema_version') != 2 or raw.get('vendor') != vendor or raw.get('scenario') != case or raw.get('target_logs_per_second') != rate or raw.get('complete') is not True or raw.get('service_unchanged') is not True:
            raise ValueError('incomplete tier, wrong identity or service restart')
        if not number(raw.get('agent_drain_observation_seconds')) or raw['agent_drain_observation_seconds'] < 60:
            raise ValueError('missing post-load observation')
        provenance_path = directory / 'provenance.json'
        generator = json.loads(provenance_path.read_text()).get('fixed_rate', {}).get('generator') if provenance_path.exists() else None
        policy(raw['loadgen'], rate, payload, generator=generator)
        m = phase(raw['loadgen'], 60); result.update(m)
        result['limits'] = raw.get('limits'); result['generator_limits'] = raw.get('generator_limits'); result['agent_drain_observation_seconds'] = raw['agent_drain_observation_seconds']
        if any(300 <= int(code) < 500 and int(code) != 429 and count for code, count in m['http_status_counts'].items()):
            raise ValueError('HTTP redirect/client rejection: invalid endpoint, payload, authentication or configuration')
        cal_path = directory / f'{vendor}_{rate}.calibration.json'
        cal = json.loads(cal_path.read_text())
        if any(cal.get(k) != raw['loadgen'].get(k) for k in ('generator', 'generator_version', 'dispatch_mode')):
            raise ValueError('calibration and measurement use different generators')
        policy(cal, rate, payload, True, generator=generator)
        calibration = phase(cal, 10, False)
        result['calibration'] = calibration
        if not attainment(calibration, rate) or calibration['scheduler_missed_logs'] > rate*10*TOLERANCE:
            result.update(status='generator_limited', sustains_target=False, reason='Standalone generator calibration did not sustain this rate')
        elif m['scheduler_missed_logs'] > rate*60*TOLERANCE:
            result.update(status='generator_limited', sustains_target=False, reason='Scheduler missed more than 2% of the target; agent capacity cannot be isolated')
        elif attainment(m, rate):
            result.update(status='ok', sustains_target=True, reason='Offered and acknowledged rates meet the 2% criterion; no unrecovered errors/backpressure')
        elif m['backpressure'] or m['errors'] or m['offered_logs_per_second'] >= rate*(1-TOLERANCE):
            result.update(status='capacity_limited', sustains_target=False, reason='Target not sustained in this colocated setup: HTTP rejection/failure or acknowledgement shortfall')
        else:
            result.update(status='generator_limited', sustains_target=False, reason='Under-offered workload without conclusive agent rejection; source/worker or shared-host contention cannot be isolated')
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError, ArithmeticError) as error:
        result.update(status='invalid', sustains_target=None, reason=str(error))
    return result


def summarize_fixed(directory, provenance, vendors, cases, unsupported):
    enabled = provenance.get('schema_version', 1) >= 2
    rates = rates_for(provenance)
    payload = provenance.get('fixed_rate', {}).get('payload_sha256')
    result = {'schema_version': 2, 'targets': rates, 'measured': enabled, 'tolerance': TOLERANCE, 'memory_unit': 'MB = 1,000,000 bytes', 'cpu_unit': '100% = one logical CPU core', 'tiers': {}, 'common_scenarios': [c for c in cases if all((v,c) not in unsupported for v in vendors)], 'common_scenario_aggregates': {}}
    for v in vendors:
        for c in cases:
            for r in rates:
                entry = {'target_logs_per_second': r, 'status': 'unsupported', 'sustains_target': None} if (v,c) in unsupported else tier(directory,v,c,r,payload) if enabled else {'target_logs_per_second': r, 'status': 'not_measured', 'sustains_target': None, 'reason': 'Historical result format; no fixed-rate measurements'}
                result['tiers'][f'{v}/{c}/{r}'] = entry
        for rate in rates:
            rows = [result['tiers'][f'{v}/{c}/{rate}'] for c in result['common_scenarios']]
            valid = all(row['status'] == 'ok' for row in rows)
            # Ratio of sums across the SAME scenarios, not an unweighted average of ratios.
            ack = sum(r['acknowledged_logs_per_second'] for r in rows) if valid else None
            cpu = sum(r['agent_cpu_percent']/100 for r in rows) if valid else None
            mem = sum(r['agent_avg_memory_mb'] for r in rows) if valid else None
            result['common_scenario_aggregates'][f'{v}/{rate}'] = {'status': 'ok' if valid else 'excluded', 'logs_per_second_per_core': ack/cpu if cpu else None, 'logs_per_second_per_mb': ack/mem if mem else None, 'cpu_microseconds_per_acknowledged_log': cpu*1e6/ack if ack else None}
    if enabled:
        supported = [t for t in result['tiers'].values() if t['status'] != 'unsupported']
        result['outcomes'] = {
            'passed': sum(t['status'] == 'ok' for t in supported),
            'failed_target': sum(t['status'] in SHORTFALL_STATUSES for t in supported),
            'not_tested_after_shortfall': sum(t['status'] == 'skipped_after_shortfall' for t in supported),
            'invalid_or_missing': sum(t['status'] not in REPORTABLE_STATUSES for t in supported),
            'generator_uncertain': sum(t['status'] == 'generator_limited' for t in supported),
        }
        result['scenario_attainment'] = {}
        for vendor in vendors:
            for case in cases:
                rows = [result['tiers'][f'{vendor}/{case}/{rate}'] for rate in rates]
                passed = [t['target_logs_per_second'] for t in rows if t['status'] == 'ok']
                failed = [t['target_logs_per_second'] for t in rows if t['status'] in SHORTFALL_STATUSES]
                result['scenario_attainment'][f'{vendor}/{case}'] = {
                    'highest_measured_sustained_target': max(passed) if passed else None,
                    'lowest_measured_failed_target': min(failed) if failed else None,
                    'unsupported': (vendor, case) in unsupported,
                }
    return result


def hardware(directory, vendors):
    result = {}
    for vendor in vendors:
        path = directory / f'hardware_{vendor}.json'
        if not path.exists() and (directory / 'hardware.json').exists():
            result[vendor] = {'runtime': json.loads((directory / 'hardware.json').read_text()), 'published': json.loads((directory / 'hardware-aws.json').read_text()) if (directory / 'hardware-aws.json').exists() else {}}
        else:
            result[vendor] = json.loads(path.read_text()) if path.exists() else {'runtime': {}, 'published': {}}
    return result


def required_assets(directory, vendors, cases, unsupported):
    rates = rates_for(json.loads((directory/'provenance.json').read_text()))
    files = [directory/'fixed-nginx.ndjson']
    for v in vendors:
        files += [directory/f'hardware_{v}.json']
        files += [directory/f'{v}_{r}.calibration.json' for r in rates]
        files += [directory/f'{v}_{c}_{r}.fixed.json' for c in cases if (v,c) not in unsupported for r in rates]
    return files


def memory_matches(hardware):
    """Keep observed MemTotal exact, but allow <=64 KiB variation for equal AWS RAM SKUs."""
    observed = [h.get('runtime', {}).get('observed', {}).get('installed_memory_bytes') for h in hardware.values()]
    if not observed or not all(number(m) and m > 0 for m in observed): return False
    published = [h.get('published', {}).get('memory_mib') for h in hardware.values()]
    if len(set(published)) > 1: return False
    if len(set(observed)) == 1: return True
    return all(number(m) and m > 0 for m in published) and max(observed)-min(observed) <= 65536


def validate_fixed(directory, data):
    errors = []
    p = data.get('provenance', {})
    if p.get('synthetic') or any(t.get('synthetic') for t in data['fixed_throughput']['tiers'].values()): errors.append('Synthetic fixtures must never be published')
    if p.get('schema_version', 1) < 2: return errors
    rates = rates_for(p)
    expected = {'targets': rates, 'workers': 256, 'warmup_seconds': 10, 'measurement_seconds': 60, 'agent_drain_seconds': 60, 'tolerance': TOLERANCE}
    if any(p.get('fixed_rate', {}).get(k) != v for k,v in expected.items()): errors.append('Incomplete fixed-rate methodology')
    corpus = directory/'fixed-nginx.ndjson'
    if not corpus.exists() or hashlib.sha256(corpus.read_bytes()).hexdigest() != p.get('fixed_rate', {}).get('payload_sha256'): errors.append('Missing or mismatched fixed-rate corpus')
    for key, t in data['fixed_throughput']['tiers'].items():
        if t['status'] not in (*REPORTABLE_STATUSES, 'unsupported'): errors.append(f'{key}: {t["status"]}: {t.get("reason")}')
        if t['status'] in MEASURED_STATUSES:
            for scope in ['limits', 'generator_limits']:
                if not isinstance(t.get(scope), dict) or not {'cpu_max', 'memory_max_bytes', 'cpuset_cpus_effective', 'main_process_cpu_affinity', 'cpu_ancestors_observed', 'memory_ancestors_observed'} <= set(t[scope]): errors.append(f'{key}: missing {scope} inspection')
    for vendor in data['hardware']:
        for rate in rates:
            try:
                cal = json.loads((directory/f'{vendor}_{rate}.calibration.json').read_text())
                policy(cal, rate, p.get('fixed_rate', {}).get('payload_sha256'), True, generator=p.get('fixed_rate', {}).get('generator'))
                phase(cal, 10, False)
            except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError, ArithmeticError) as error:
                errors.append(f'{vendor}/{rate}: invalid calibration: {error}')
    observed = []
    for vendor, h in data['hardware'].items():
        o = h.get('runtime', {}).get('observed', {})
        if not o.get('logical_cpus') or not o.get('installed_memory_bytes') or not o.get('os') or not o.get('kernel'): errors.append(f'{vendor}: incomplete runtime hardware inspection')
        observed.append(tuple(o.get(k) for k in ['instance_type', 'region', 'logical_cpus', 'architecture', 'cpu_model', 'os', 'kernel']))
    storage = [json.dumps(h.get('published', {}).get('volumes'), sort_keys=True) for h in data['hardware'].values()]
    if len(set(storage)) > 1: errors.append('Agent AWS volume configurations differ')
    limits = [json.dumps(t.get('limits'), sort_keys=True) for t in data['fixed_throughput']['tiers'].values() if t['status'] in MEASURED_STATUSES]
    generator_limits = {json.dumps(t.get('generator_limits'), sort_keys=True) for t in data['fixed_throughput']['tiers'].values() if t['status'] in MEASURED_STATUSES}
    if len(generator_limits) > 1: errors.append('Generator CPU/memory limits differ across tiers or agents')
    if len(set(limits)) > 1: errors.append('Agent CPU/memory limits differ across agents or tiers')
    if len(set(observed)) > 1 or not memory_matches(data['hardware']): errors.append('Agent runtime machine configurations differ')
    return errors


def apply_comparability(data):
    """Do not compare runs on unknown/different hardware or service limits."""
    fingerprints = []
    known = True
    for h in data['hardware'].values():
        o = h.get('runtime', {}).get('observed', {})
        keys = ['instance_type', 'region', 'logical_cpus', 'architecture', 'cpu_model', 'os', 'kernel']
        known = known and all(o.get(k) is not None for k in keys)
        fingerprints.append(json.dumps([*[o.get(k) for k in keys], h.get('published', {}).get('volumes')], sort_keys=True))
    limits = {json.dumps(t.get('limits'), sort_keys=True) for t in data['fixed_throughput']['tiers'].values() if t['status'] in MEASURED_STATUSES}
    generator_limits = {json.dumps(t.get('generator_limits'), sort_keys=True) for t in data['fixed_throughput']['tiers'].values() if t['status'] in MEASURED_STATUSES}
    known = known and all((t.get(scope) or {}).get('cpu_ancestors_observed') and (t.get(scope) or {}).get('memory_ancestors_observed') for t in data['fixed_throughput']['tiers'].values() if t['status'] in MEASURED_STATUSES for scope in ['limits', 'generator_limits'])
    comparable = memory_matches(data['hardware']) and len(generator_limits) == 1 and known and len(set(fingerprints)) == 1 and len(limits) == 1
    data['fixed_throughput']['matching_environment'] = comparable
    for t in data['fixed_throughput']['tiers'].values():
        t['comparison_eligible'] = comparable and t['status'] == 'ok'
    if not comparable:
        for aggregate in data['fixed_throughput']['common_scenario_aggregates'].values():
            aggregate.update(status='excluded: unknown/different environment', logs_per_second_per_core=None, logs_per_second_per_mb=None, cpu_microseconds_per_acknowledged_log=None)
