#!/usr/bin/env python3
"""Plan isolated agent jobs and combine only their complete measured results."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import fixed
from summarize import VENDORS, CASES, UNSUPPORTED, parse_log, summarize

ROOT = Path(__file__).resolve().parents[1]

def plan(vendors, cases):
    result = subprocess.run([str(ROOT / 'run.sh'), '--dry-run', '--vendors', vendors, '--cases', cases], check=True, capture_output=True, text=True)
    jobs = []
    for line in result.stdout.splitlines():
        vendor, separator, selected = line.partition(': ')
        if separator and vendor in VENDORS and selected.strip():
            jobs.append({'vendor': vendor, 'cases': ','.join(selected.split())})
    if not jobs:
        raise ValueError('No supported scenarios selected')
    return {'include': jobs}

def merge(source, output, matrix, require_fixed=False):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Output directory must not exist')
    expected = {job['vendor']: job['cases'].split(',') for job in matrix['include']}
    shards, files, versions, instances = {}, [], [], set()
    hardware = {}
    corpus_bytes = None
    for version_file in source.rglob('versions.csv'):
        if any(part.endswith('-combined') for part in version_file.relative_to(source).parts): continue
        with version_file.open() as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 1 or rows[0]['agent'] not in expected:
            raise ValueError('Unexpected shard version set')
        vendor = rows[0]['agent']
        if vendor in shards or not rows[0]['version'] or rows[0]['version'].strip().lower() == 'unknown':
            raise ValueError('Duplicate shard or missing version')
        directory = version_file.parent
        provenance = json.loads((directory / 'provenance.json').read_text())
        if require_fixed and (provenance.get('schema_version', 1) < 3 or provenance.get('fixed_rate', {}).get('targets') != fixed.RATES): raise ValueError('Daily suite requires measured fixed-rate results including 125k')
        instance = provenance.get('instance_id')
        if not instance or instance in instances:
            raise ValueError('Missing or shared instance identity')
        instances.add(instance)
        for case in expected[vendor]:
            log = directory / f'{vendor}_{case}.log'
            data = parse_log(log.read_text(), require_retries=bool(provenance.get('loadgen', {}).get('retry_ambiguous')))
            if data['status'] not in ('ok', 'errors') or any(data.get(k) is None for k in ['avg', 'peak', 'total', 'cpu', 'mem']):
                raise ValueError(f'Incomplete measurement: {vendor}/{case}')
            files.append(log)
        if provenance.get('schema_version', 1) >= 2:
            hardware[vendor] = {'runtime': json.loads((directory/'hardware.json').read_text()), 'published': json.loads((directory/'hardware-aws.json').read_text())}
            corpus = (directory/'fixed-nginx.ndjson').read_bytes()
            if corpus_bytes is not None and corpus != corpus_bytes: raise ValueError('Shard payloads differ')
            corpus_bytes = corpus
            for rate in fixed.rates_for(provenance):
                files.append(directory/f'{vendor}_{rate}.calibration.json')
                for case in expected[vendor]:
                    entry = fixed.tier(directory, vendor, case, rate, provenance['fixed_rate']['payload_sha256'])
                    if entry['status'] not in fixed.REPORTABLE_STATUSES: raise ValueError(f'{vendor}/{case}/{rate}: {entry["status"]}: {entry["reason"]}')
                    files.append(directory/f'{vendor}_{case}_{rate}.fixed.json')
        shards[vendor] = provenance
        versions += rows
    if set(shards) != set(expected):
        raise ValueError('Missing agent shards')
    first = next(iter(shards.values()))
    for shard in shards.values():
        for key in ['benchmark_commit', 'loadgen_version', 'loadgen', 'workers', 'duration_per_tier_seconds', 'period', 'instance_type', 'region', 'pipeline_sha256', 'schema_version', 'fixed_rate']:
            if shard.get(key) != first.get(key):
                raise ValueError(f'Shard methodology differs: {key}')
    combined = dict(first, execution_mode='parallel agents on separate identical EC2 instances; sequential cases and tiers per agent', shards=shards)
    for key in ['rust_commit', 'rust_release', 'red_binary_sha256']:
        combined.pop(key, None)
        if key in shards.get('red', {}):
            combined[key] = shards['red'][key]
    combined.pop('instance_id', None)
    output.mkdir(parents=True)
    for vendor, facts in hardware.items():
        (output/f'hardware_{vendor}.json').write_text(json.dumps(facts, indent=2)+'\n')
    if corpus_bytes is not None: (output/'fixed-nginx.ndjson').write_bytes(corpus_bytes)
    for log in files:
        shutil.copyfile(log, output / log.name)
    with (output / 'versions.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['agent', 'version']); writer.writeheader(); writer.writerows(versions)
    (output / 'provenance.json').write_text(json.dumps(combined, indent=2) + '\n')
    summarize(output)
    if set(expected) == set(VENDORS) and all(set(cases) == {c for c in CASES if (v, c) not in UNSUPPORTED} for v, cases in expected.items()):
        from check_results import validate
        validate(output)
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan'); p.add_argument('vendors'); p.add_argument('cases')
    p = sub.add_parser('merge'); p.add_argument('source'); p.add_argument('output'); p.add_argument('matrix'); p.add_argument('--require-fixed', action='store_true')
    args = parser.parse_args()
    if args.command == 'plan': print(json.dumps(plan(args.vendors, args.cases)))
    else: print(merge(args.source, args.output, json.loads(args.matrix), args.require_fixed))
