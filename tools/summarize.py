#!/usr/bin/env python3
"""Generate release tables and chart data from raw loadgen logs; never publish."""
import argparse
import csv
import datetime
import json
from pathlib import Path
import re
import statistics
import fixed
import fixed_report

VENDORS = {'edgedelta': ('ed', 'Edge Delta (Go)'), 'red': ('red', 'Edge Delta (Rust)'), 'cribl': ('cribl', 'Cribl'), 'otelcol': ('otel', 'OpenTelemetry Collector'), 'fluentd': ('fluentd', 'Fluentd'), 'vector': ('vector', 'Vector'), 'fluentbit': ('fluentbit', 'Fluent Bit')}
RETRY_FIELDS = ['connection_errors', 'retry_attempts', 'recovered_requests', 'ambiguous_deliveries']
CASES = ['pass-through', 'filter', 'mask', 'lookup']
UNSUPPORTED = {('otelcol', 'lookup'), ('fluentbit', 'mask')}


def parse_log(text, require_retries=False):
    runs = []
    current = None
    for line in text.splitlines():
        start = re.match(r'Starting loadgen with (\d+) workers', line)
        if start:
            current = {'workers': int(start[1]), 'avg': None, 'peak': None, 'total': None, 'errors': None, 'backpressure': None, 'cpu': [], 'mem': [], 'processes': {}, 'complete': False}
            current.update({field: None for field in RETRY_FIELDS})
            runs.append(current)
        if current is None:
            continue
        if '[STATS]' in line:
            avg = re.search(r'avg: ([\d.]+) logs/sec', line)
            peak = re.search(r'current: ([\d.]+) logs/sec', line)
            if avg:
                current['avg'] = float(avg[1])
            if peak:
                current['peak'] = max(current['peak'] or 0, float(peak[1]))
            for field in ['total', 'errors', 'backpressure'] + RETRY_FIELDS:
                value = re.search(r'\b' + field + r': (\d+)', line)
                if value:
                    current[field] = max(current[field] or 0, int(value[1]))
        if '[MONITOR - TARGET]' in line:
            values = re.search(r'cpu: ([\d.]+)% \| memory: ([\d.]+)MB', line)
            if values:
                current['cpu'].append(float(values[1]))
                current['mem'].append(float(values[2]))
                pid = re.search(r'pid: (\d+)', line)
                process = current['processes'].setdefault(pid[1] if pid else 'unknown', {'cpu': [], 'mem': []})
                process['cpu'].append(float(values[1]))
                process['mem'].append(float(values[2]))
        end = re.match(r'Finished loadgen with (\d+) workers', line)
        if end and int(end[1]) == current['workers']:
            current['complete'] = True
    valid = len(runs) == 3 and [r['workers'] for r in runs] == [80, 100, 120] and all(r['complete'] and r['avg'] is not None and r['errors'] is not None for r in runs) and 'ERROR:' not in text
    if require_retries or any(r[f] is not None for r in runs for f in RETRY_FIELDS):
        valid = valid and all(all(r[f] is not None for f in RETRY_FIELDS) for r in runs)
        if valid:
            valid = all(r['recovered_requests'] <= r['retry_attempts']
                        and r['ambiguous_deliveries'] <= r['connection_errors']
                        and (r['total'] is None or (r['retry_attempts'] <= 2 * r['total']
                             and r['recovered_requests'] + r['errors'] <= r['total'])) for r in runs)
    status = ('errors' if any(r['errors'] for r in runs) else 'ok') if valid else 'invalid'
    result = {'status': status, 'workers': runs}
    if valid:
        best = max(runs, key=lambda r: r['avg'])
        result.update(avg=best['avg'], peak=best['peak'], best_workers=best['workers'], total=best['total'], cpu=sum(statistics.mean(p['cpu']) for p in best['processes'].values()) if best['processes'] else None, mem=sum(max(p['mem']) for p in best['processes'].values()) if best['processes'] else None, tier_mean=statistics.mean(r['avg'] for r in runs))
    return result


def fmt(value, suffix='', decimals=2):
    return 'N/A' if value is None else f'{value:,.{decimals}f}{suffix}'


def report(result):
    lines = ['# Benchmark Report', '', f"**Date:** {result['date']}", f"**Run ID:** {result['runId']}", '', '## Tested Agent Versions', '', '| Vendor | Version |', '|---|---|']
    for key, name in VENDORS.values():
        lines.append(f"| {name} | {result['versions'].get(key, 'Not recorded')} |")
    lines += ['', '## Methodology', '', '- Best-throughput harness configuration and execution topology are recorded in provenance; runtime hardware is listed below when available. Historical missing hardware remains N/A.', f"- loadgen {result.get('provenance', {}).get('loadgen_version', 'version not recorded')}, nginx JSON, 80 / 100 / 120 workers, 1 ms send period, 60 seconds per tier, 60-second drain intervals.", '- The tier with the highest final cumulative average is reported for each scenario, matching the reference release’s best-tier convention. Peak, total logs, CPU, and memory come from that same tier. All tiers remain in data.json and the raw logs.', '- Peak throughput is the largest sampled interval rate (approximately 5 seconds). CPU sums each monitored process’s average; memory sums per-process peak RSS (these peaks need not occur simultaneously). CPU uses 100% per core.', '- These are HTTP ingestion measurements, not verified durable S3 throughput. Buffering, compression, schemas, and acknowledgment semantics differ by product. Process monitoring can omit auxiliary processes, particularly for multi-process agents.', '- Reliability tables aggregate cumulative errors/backpressure once per tier across all three tiers. Missing fields remain N/A; incomplete runs invalidate the scenario. Completed runs with unrecovered request failures retain measured values and an errors status, but are excluded from ranks and cross-scenario charts. Recovered connection failures do not exclude a result.', '']
    provenance = result.get('provenance', {})
    if provenance.get('loadgen', {}).get('retry_ambiguous'):
        lines += ['**Delivery policy:** At least once with possible duplicates; up to two connection-failure retries on fresh connections within the original request timeout. HTTP error responses and timeouts are not retried. Throughput counts acknowledged logical batches once and includes retry time; this suite sends one log per batch. Ambiguous deliveries count logical requests that might have been accepted before a connection failure, including recovered requests. These are not confirmed losses or duplicate counts. Connection and retry counters exclude safe retries internal to Go’s HTTP transport.', '']
    if provenance:
        lines += [f"**Execution:** {provenance.get('execution_mode', 'sequential (one instance)')}", '']
        if provenance.get('rust_release'):
            lines += [f"**Rust release:** {provenance['rust_release']['version']} (verified released binary)", '']
        lines += [f"**Benchmark source:** `{provenance.get('benchmark_commit', 'unknown')}`", f"**Rust source:** `{provenance.get('rust_commit') or 'N/A (released binary)' }`", '']
    lines += fixed_report.report(result, VENDORS, CASES)
    for case in CASES:
        lines += [f'## Benchmark Scenario: {case.title()}', '', '### Performance Comparison', '', '| Vendor | Status | Best Workers | Avg Throughput | Peak Throughput | Total Logs | Avg CPU | Peak Memory | Rank |', '|---|---|---:|---:|---:|---:|---:|---:|---:|']
        rows = [(vendor, name, result['scenarios'][f'{vendor}/{case}']) for vendor, (_, name) in VENDORS.items()]
        rows.sort(key=lambda row: -(row[2].get('avg') or 0))
        rank = 0
        for vendor, name, data in rows:
            if data['status'] in ('ok', 'errors'):
                if data['status'] == 'ok':
                    rank += 1
                ranking = rank if data['status'] == 'ok' else 'N/A'
                lines.append(f"| {name} | {data['status']} | {data['best_workers']} | {fmt(data['avg'], ' logs/sec')} | {fmt(data['peak'], ' logs/sec')} | {fmt(data['total'], decimals=0)} | {fmt(data['cpu'], '%', 1)} | {fmt(data['mem'], ' MiB', 1)} | {ranking} |")
            else:
                lines.append(f"| {name} | {data['status']} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
        lines += ['', '### Reliability Comparison', '', '| Vendor | Unrecovered Errors (all tiers) | Backpressure (all tiers) | Status |', '|---|---:|---:|---|']
        for vendor, name, data in rows:
            tiers = data.get('workers', [])
            def total(field):
                return sum(w[field] for w in tiers) if tiers and all(w[field] is not None for w in tiers) else None
            lines.append(f"| {name} | {fmt(total('errors'), decimals=0)} | {fmt(total('backpressure'), decimals=0)} | {data['status']} |")
        lines += ['', '### Connection Recovery (all tiers)', '', '| Vendor | Connection Errors | Retry Attempts | Recovered Requests | Ambiguous Deliveries |', '|---|---:|---:|---:|---:|']
        for vendor, name, data in rows:
            tiers = data.get('workers', [])
            values = [sum(w[field] for w in tiers) if tiers and all(w.get(field) is not None for w in tiers) else None for field in RETRY_FIELDS]
            lines.append('| ' + name + ' | ' + ' | '.join(fmt(v, decimals=0) for v in values) + ' |')
        lines.append('')
    lines += ['## Cross-Scenario Summary', '']
    for metric, title in [('avg', 'Average Throughput (logs/sec)'), ('peak', 'Peak Throughput (logs/sec)')]:
        lines += [f'### {title}', '', '| Vendor | Pass-Through | Filter | Mask | Lookup |', '|---|---:|---:|---:|---:|']
        for key, name in VENDORS.values():
            values = ' | '.join(fmt(x) for x in result['vendors'][key][metric])
            lines.append(f'| {name} | {values} |')
        lines.append('')
    lines += ['### Resource Efficiency (Across Supported Scenarios)', '', 'Descriptive legacy values only; scenario coverage differs by agent, so this table is not a cross-agent efficiency ranking. Use the matching-scenario fixed-rate aggregates for comparisons. Legacy memory is MiB (2²⁰ bytes), historically labeled MB in raw logs.', '', '| Vendor | Avg CPU | Avg Peak Memory | Throughput per CPU % |', '|---|---:|---:|---:|']
    for key, name in VENDORS.values():
        data = result['vendors'][key]
        lines.append(f"| {name} | {fmt(data['cpu'], '%', 1)} | {fmt(data['mem'], ' MiB', 1)} | {fmt(data['perCpu'])} |")
    lines += ['', '## Coverage and limitations', '', 'OTel CSV lookup and Fluent Bit regex masking are unsupported by this suite. Fluent Bit lookup uses a Lua table loaded from the bundled CSV. The inherited masking implementations scan different fields; this report is not proof of semantic equivalence or a general product ranking.', '', 'The assets include raw logs, recorded versions, source/config provenance, structured data, and this report. No values have been filled from earlier releases.']
    if result.get('synthetic'): lines.insert(0, '> **SYNTHETIC FIXTURE PREVIEW — all numbers and versions below are illustrative test data, not real benchmark measurements. DO NOT PUBLISH.**\n')
    return '\n'.join(lines) + '\n'


def summarize(directory):
    run_id = directory.name
    date = re.sub(r'[^0-9]', '', run_id)[:8]
    date = f'{date[:4]}-{date[4:6]}-{date[6:8]}' if len(date) == 8 else datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    result = {'runId': run_id, 'date': date, 'aggregation': 'best-tier', 'vendors': {}, 'versions': {}, 'scenarios': {}}
    version_file = directory / 'versions.csv'
    if version_file.exists():
        with version_file.open() as stream:
            for row in csv.DictReader(stream):
                if row['agent'] in VENDORS:
                    result['versions'][VENDORS[row['agent']][0]] = row['version']
    if (directory / 'provenance.json').exists():
        result['provenance'] = json.loads((directory / 'provenance.json').read_text())
    for vendor, (key, name) in VENDORS.items():
        metrics = {'name': name, 'avg': [None] * 4, 'peak': [None] * 4, 'cpu': None, 'mem': None, 'perCpu': None}
        result['vendors'][key] = metrics
        valid_cases = []
        for index, case in enumerate(CASES):
            path = directory / f'{vendor}_{case}.log'
            unsupported = (vendor, case) in UNSUPPORTED
            parsed = {'status': 'unsupported' if unsupported else 'not-run'}
            if path.exists() and not unsupported:
                parsed = parse_log(path.read_text(), require_retries=bool(result.get('provenance', {}).get('loadgen', {}).get('retry_ambiguous')))
            result['scenarios'][f'{vendor}/{case}'] = parsed
            if parsed['status'] == 'ok':
                valid_cases.append(parsed)
                metrics['avg'][index] = parsed['avg']
                metrics['peak'][index] = parsed['peak']
        if valid_cases:
            if all(c['cpu'] is not None for c in valid_cases):
                metrics['cpu'] = statistics.mean(c['cpu'] for c in valid_cases)
            if all(c['mem'] is not None for c in valid_cases):
                metrics['mem'] = statistics.mean(c['mem'] for c in valid_cases)
            if metrics['cpu']:
                metrics['perCpu'] = statistics.mean(c['avg'] for c in valid_cases) / metrics['cpu']
    result['fixed_throughput'] = fixed.summarize_fixed(directory, result.get('provenance', {}), VENDORS, CASES, UNSUPPORTED)
    result['hardware'] = fixed.hardware(directory, VENDORS)
    fixed.apply_comparability(result)
    if result.get('provenance', {}).get('synthetic'): result['synthetic'] = True
    (directory / 'data.json').write_text(json.dumps(result, indent=2) + '\n')
    (directory / 'report.md').write_text(report(result))
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error('results directory does not exist')
    summarize(args.directory)
