#!/usr/bin/env python3
"""Plan isolated agent jobs and combine only their complete measured results."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import re
import subprocess
from summarize import VENDORS, CASES, UNSUPPORTED, parse_log, summarize

ROOT = Path(__file__).resolve().parents[1]

def plan(vendors, cases):
    result = subprocess.run([str(ROOT / 'run.sh'), '--dry-run', '--vendors', vendors, '--cases', cases], check=True, capture_output=True, text=True)
    jobs = []
    for line in result.stdout.splitlines():
        vendor, separator, selected = line.partition(': ')
        if separator and vendor in VENDORS and selected.strip():
            jobs.extend({'vendor': vendor, 'cases': case} for case in selected.split())
    if not jobs:
        raise ValueError('No supported scenarios selected')
    return {'include': jobs}

def merge(source, output, matrix):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Output directory must not exist')
    expected = {(job['vendor'], job['cases']) for job in matrix['include']}
    if len(expected) != len(matrix['include']) or any(v not in VENDORS or c not in CASES or (v, c) in UNSUPPORTED for v, c in expected):
        raise ValueError('Expected unique supported agent/scenario jobs')
    shards, files, versions, instances = {}, [], {}, set()
    for version_file in source.rglob('versions.csv'):
        with version_file.open() as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 1 or rows[0]['agent'] not in {v for v, _ in expected}:
            raise ValueError('Unexpected shard version set')
        vendor = rows[0]['agent']
        if not rows[0]['version'] or rows[0]['version'].strip().lower() == 'unknown':
            raise ValueError('Duplicate shard or missing version')
        directory = version_file.parent
        provenance = json.loads((directory / 'provenance.json').read_text())
        logs = list(directory.glob('*.log'))
        cases = [c for v, c in expected if v == vendor and (directory / f'{v}_{c}.log').exists()]
        if len(cases) != 1 or len(logs) != 1:
            raise ValueError('Each shard must contain exactly one expected scenario')
        case = cases[0]
        shard_key = f'{vendor}/{case}'
        if shard_key in shards:
            raise ValueError('Duplicate scenario shard')
        # Go's default build time can reflect invocation time; version and commit identify the build.
        version = re.sub(r', built on:.*$', '', rows[0]['version']) if vendor == 'edgedelta' else rows[0]['version']
        if vendor in versions and versions[vendor] != version:
            raise ValueError(f'Installed versions differ between {vendor} scenarios')
        versions[vendor] = version
        instance = provenance.get('instance_id')
        if not instance or instance in instances:
            raise ValueError('Missing or shared instance identity')
        instances.add(instance)
        for case in cases:
            log = directory / f'{vendor}_{case}.log'
            data = parse_log(log.read_text(), require_retries=bool(provenance.get('loadgen', {}).get('retry_ambiguous')))
            if data['status'] not in ('ok', 'errors') or any(data.get(k) is None for k in ['avg', 'peak', 'total', 'cpu', 'mem']):
                raise ValueError(f'Incomplete measurement: {vendor}/{case}')
            files.append(log)
        shards[shard_key] = provenance
    if set(shards) != {f'{v}/{c}' for v, c in expected}:
        raise ValueError('Missing agent shards')
    first = next(iter(shards.values()))
    for shard in shards.values():
        for key in ['benchmark_commit', 'loadgen_version', 'loadgen', 'workers', 'duration_per_tier_seconds', 'period', 'instance_type', 'region', 'pipeline_sha256']:
            if shard.get(key) != first.get(key):
                raise ValueError(f'Shard methodology differs: {key}')
    fleets = [s.get('cribl_fleet_id') for key, s in shards.items() if key.startswith('cribl/')]
    if any(not f for f in fleets) or len(set(fleets)) != len(fleets):
        raise ValueError('Missing or shared Cribl fleet identity')
    rust_shards = [s for key, s in shards.items() if key.startswith('red/')]
    for key in ['rust_commit', 'rust_release', 'red_binary_sha256']:
        if rust_shards and any(s.get(key) != rust_shards[0].get(key) for s in rust_shards):
            raise ValueError('Rust artifacts differ between scenarios')
    combined = dict(first, execution_mode='parallel agent/scenario pairs on separate identical EC2 instances; sequential worker tiers per scenario', shards=shards)
    for key in ['rust_commit', 'rust_release', 'red_binary_sha256']:
        combined.pop(key, None)
        if rust_shards and key in rust_shards[0]:
            combined[key] = rust_shards[0][key]
    combined.pop('instance_id', None)
    combined.pop('cribl_fleet_id', None)
    output.mkdir(parents=True)
    for log in files:
        shutil.copyfile(log, output / log.name)
    with (output / 'versions.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['agent', 'version']); writer.writeheader(); writer.writerows({'agent': v, 'version': versions[v]} for v in VENDORS if v in versions)
    (output / 'provenance.json').write_text(json.dumps(combined, indent=2) + '\n')
    summarize(output)
    if expected == {(v, c) for v in VENDORS for c in CASES if (v, c) not in UNSUPPORTED}:
        from check_results import validate
        validate(output)
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan'); p.add_argument('vendors'); p.add_argument('cases')
    p = sub.add_parser('merge'); p.add_argument('source'); p.add_argument('output'); p.add_argument('matrix')
    args = parser.parse_args()
    if args.command == 'plan': print(json.dumps(plan(args.vendors, args.cases)))
    else: print(merge(args.source, args.output, json.loads(args.matrix)))
