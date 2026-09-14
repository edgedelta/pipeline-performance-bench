#!/usr/bin/env python3
"""Check full-suite release coverage and write checksums for publishable assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from summarize import CASES, UNSUPPORTED, VENDORS, summarize


def validate(directory):
    data = summarize(directory)
    errors = []
    for vendor, (key, _) in VENDORS.items():
        version = data['versions'].get(key, '')
        if not version or version.strip().lower() in ('unknown', 'not recorded'):
            errors.append(f'{vendor}: missing recorded version')
        for case in CASES:
            if (vendor, case) in UNSUPPORTED:
                continue
            entry = data['scenarios'][f'{vendor}/{case}']
            if entry['status'] not in ('ok', 'errors'):
                errors.append(f'{vendor}/{case}: {entry["status"]}')
                continue
            for field in ['avg', 'peak', 'total', 'cpu', 'mem']:
                if entry.get(field) is None:
                    errors.append(f'{vendor}/{case}: missing {field}')
            if entry['avg'] <= 0 or (entry.get('total') or 0) <= 0:
                errors.append(f'{vendor}/{case}: no measured throughput')
    for field in ['benchmark_commit', 'rust_commit']:
        if not re.fullmatch(r'[a-f0-9]{40}', data.get('provenance', {}).get(field) or ''):
            errors.append(f'missing {field} provenance')
    expected_logs = [directory / f'{vendor}_{case}.log' for vendor in VENDORS for case in CASES if (vendor, case) not in UNSUPPORTED]
    files = expected_logs + [directory / name for name in ['versions.csv', 'provenance.json', 'data.json', 'report.md']]
    secret = re.compile(r'(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----')
    for path in files:
        if not path.is_file():
            errors.append(f'missing asset {path.name}')
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
