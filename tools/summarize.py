#!/usr/bin/env python3
"""Produce a reviewable report from loadgen logs; never fetch or publish data."""
import argparse
import csv
import datetime
import json
from pathlib import Path
import re
import statistics

VENDORS = {'edgedelta': ('ed', 'Edge Delta (Go)'), 'red': ('red', 'Edge Delta (Rust)'), 'cribl': ('cribl', 'Cribl'), 'otelcol': ('otel', 'OpenTelemetry Collector'), 'fluentd': ('fluentd', 'Fluentd'), 'vector': ('vector', 'Vector'), 'fluentbit': ('fluentbit', 'Fluent Bit')}
CASES = ['pass-through', 'filter', 'mask', 'lookup']


def parse_log(text):
    runs = []
    current = None
    for line in text.splitlines():
        start = re.match(r'Starting loadgen with (\d+) workers', line)
        if start:
            current = {'workers': int(start[1]), 'avg': None, 'peak': 0, 'errors': 0, 'cpu': [], 'mem': [], 'complete': False}
            runs.append(current)
        if current is None:
            continue
        if '[STATS]' in line:
            avg = re.search(r'avg: ([\d.]+) logs/sec', line)
            peak = re.search(r'current: ([\d.]+) logs/sec', line)
            errors = re.search(r'errors: (\d+)', line)
            if avg:
                current['avg'] = float(avg[1])
                current['peak'] = max(current['peak'], float((peak or avg)[1]))
            if errors:
                current['errors'] = max(current['errors'], int(errors[1]))
        if '[MONITOR - TARGET]' in line:
            values = re.search(r'cpu: ([\d.]+)% \| memory: ([\d.]+)MB', line)
            if values:
                current['cpu'].append(float(values[1]))
                current['mem'].append(float(values[2]))
        end = re.match(r'Finished loadgen with (\d+) workers', line)
        if end and int(end[1]) == current['workers']:
            current['complete'] = True
    valid = len(runs) == 3 and [r['workers'] for r in runs] == [80, 100, 120] and all(r['complete'] and r['avg'] is not None and r['errors'] == 0 for r in runs) and 'ERROR:' not in text
    result = {'status': 'ok' if valid else 'invalid', 'workers': runs}
    if valid:
        result.update(avg=statistics.mean(r['avg'] for r in runs), peak=max(r['peak'] for r in runs))
    return result


def summarize(directory):
    run_id = directory.name
    date = re.sub(r'[^0-9]', '', run_id)[:8]
    date = f'{date[:4]}-{date[4:6]}-{date[6:8]}' if len(date) == 8 else datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    result = {'runId': run_id, 'date': date, 'vendors': {}, 'versions': {}, 'scenarios': {}}
    version_file = directory / 'versions.csv'
    if version_file.exists():
        for row in csv.DictReader(version_file.open()):
            if row['agent'] in VENDORS:
                result['versions'][VENDORS[row['agent']][0]] = row['version']
    lines = ['# Pipeline performance bench', '', 'HTTP ingestion measurements; these do not establish durable S3 delivery throughput.', '', '| Agent | Case | Status | Average logs/s | Peak sampled logs/s |', '|---|---|---|---:|---:|']
    for vendor, (key, name) in VENDORS.items():
        metrics = {'name': name, 'avg': [None] * 4, 'peak': [None] * 4, 'cpu': None, 'mem': None, 'perCpu': None}
        result['vendors'][key] = metrics
        for index, case in enumerate(CASES):
            path = directory / f'{vendor}_{case}.log'
            unsupported = (vendor, case) in [('otelcol', 'lookup'), ('fluentbit', 'mask')]
            parsed = {'status': 'unsupported' if unsupported else 'not-run'}
            if path.exists() and not unsupported:
                parsed = parse_log(path.read_text())
            result['scenarios'][f'{vendor}/{case}'] = parsed
            if parsed['status'] == 'ok':
                metrics['avg'][index] = parsed['avg']
                metrics['peak'][index] = parsed['peak']
                if case == 'pass-through':
                    cpu = [x for w in parsed['workers'] for x in w['cpu']]
                    mem = [x for w in parsed['workers'] for x in w['mem']]
                    metrics['cpu'] = statistics.mean(cpu) if cpu else None
                    metrics['mem'] = statistics.mean(mem) if mem else None
                    metrics['perCpu'] = parsed['avg'] / (metrics['cpu'] / 100) if metrics['cpu'] else None
                lines.append(f"| {name} | {case} | ok | {parsed['avg']:.2f} | {parsed['peak']:.2f} |")
            else:
                lines.append(f"| {name} | {case} | {parsed['status']} | N/A | N/A |")
    (directory / 'data.json').write_text(json.dumps(result, indent=2) + '\n')
    (directory / 'report.md').write_text('\n'.join(lines) + '\n')
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error('results directory does not exist')
    summarize(args.directory)
