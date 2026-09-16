#!/usr/bin/env python3
"""Check full-suite release coverage and write checksums for publishable assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import fixed
import capacity
from summarize import CASES, UNSUPPORTED, VENDORS, summarize


def validate(directory):
    directory = Path(directory)
    (directory / 'SHA256SUMS').unlink(missing_ok=True)
    data = summarize(directory)
    if data.get('provenance', {}).get('benchmark_profile') == 'short':
        raise ValueError('Short validation runs cannot be published as benchmark releases')
    errors = fixed.validate_fixed(directory, data)
    rust_search = capacity.enabled(data.get('provenance', {}))
    for vendor, (key, _) in VENDORS.items():
        version = data['versions'].get(key, '')
        if not version or version.strip().lower() in ('unknown', 'not recorded'):
            errors.append(f'{vendor}: missing recorded version')
        for case in CASES:
            if (vendor, case) in UNSUPPORTED:
                continue
            entry = data['scenarios'][f'{vendor}/{case}']
            if rust_search:
                if entry['status'] not in capacity.OUTCOMES:
                    errors.append(f'{vendor}/{case}: {entry["status"]}: {entry.get("reason")}')
                continue
            if entry['status'] not in ('ok', 'errors'):
                errors.append(f'{vendor}/{case}: {entry["status"]}')
                continue
            for field in ['avg', 'peak', 'total', 'cpu', 'mem']:
                if entry.get(field) is None:
                    errors.append(f'{vendor}/{case}: missing {field}')
            if entry['avg'] <= 0 or (entry.get('total') or 0) <= 0:
                errors.append(f'{vendor}/{case}: no measured throughput')
    for field in ['benchmark_commit']:
        if not re.fullmatch(r'[a-f0-9]{40}', data.get('provenance', {}).get(field) or ''):
            errors.append(f'missing {field} provenance')
    provenance = data.get('provenance', {})
    release = provenance.get('rust_release', {})
    if not (re.fullmatch(r'[a-f0-9]{40}', provenance.get('rust_commit') or '') or
            re.fullmatch(r'[a-f0-9]{64}', release.get('binary_sha256') or '') or
            re.fullmatch(r'[a-f0-9]{64}', provenance.get('red_binary_sha256') or '')):
        errors.append('missing Rust source or binary provenance')
    expected_logs = [directory / f'{vendor}_{case}.log' for vendor in VENDORS for case in CASES if (vendor, case) not in UNSUPPORTED] if not rust_search else []
    if rust_search:
        for vendor in VENDORS:
            for case in CASES:
                if (vendor, case) not in UNSUPPORTED:
                    expected_logs += capacity.assets(directory, vendor, case, data['scenarios'][f'{vendor}/{case}'])
    files = expected_logs + [directory / name for name in ['versions.csv', 'provenance.json', 'data.json', 'report.md']]
    if data.get('provenance', {}).get('schema_version', 1) >= 2:
        files += fixed.required_assets(directory, VENDORS, CASES, UNSUPPORTED)
    files = sorted(set(files))
    secret = re.compile(r'(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----')
    for path in files:
        if not path.is_file():
            errors.append(f'missing asset {path.name}')
        elif path.suffix == '.json' and json.loads(path.read_text()).get('synthetic'):
            errors.append(f'Synthetic fixture asset cannot be published: {path.name}')
        elif secret.search(path.read_text()):
            errors.append(f'possible credential in {path.name}; review required')
    if errors:
        raise ValueError('\n'.join(errors))
    sums = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in sorted(files)]
    (directory / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    return data

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        validate(args.directory)
    except (ValueError, FileNotFoundError) as error:
        parser.exit(1, f'Release validation failed:\n{error}\n')
    print('All 26 supported scenarios and seven versions validated; SHA256SUMS written.')
