"""Publish a complete daily OTLP pair and its raw evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import gh_release


def gh(*args):
    return gh_release.run(*args)


def merge_signal(paths, signal, commit, profile='full'):
    from otlp_daily import RATES, SCENARIOS, TRACE_SCENARIOS, VENDORS
    rates = RATES[signal] if profile == 'full' else RATES[signal][:1]
    scenarios = TRACE_SCENARIOS if signal == 'traces' else SCENARIOS
    shards = [json.loads(path.read_text()) for path in paths]
    if len(shards) != len(VENDORS):
        raise ValueError(f'{signal}: expected one shard per vendor')
    seen, rows, calibrations, versions = set(), [], [], {}
    first = shards[0]
    for data in shards:
        vendors = data.get('vendors', [])
        if len(vendors) != 1 or vendors[0] not in VENDORS or vendors[0] in seen:
            raise ValueError('Unexpected or duplicate vendor shard')
        vendor = vendors[0]
        seen.add(vendor)
        if data.get('signal') != signal or data.get('profile') != profile or data.get('benchmark_commit') != commit:
            raise ValueError('Shard signal/profile/commit mismatch')
        for key in ['schema', 'source_commit', 'binary_sha256', 'rust_release', 'seconds', 'batch', 'trials', 'run_url']:
            if data.get(key) != first.get(key):
                raise ValueError(f'Shard methodology differs: {key}')
        if data.get('rates') != rates or data.get('scenarios') != scenarios:
            raise ValueError('Shard ladder differs')
        expected = {(scenario, rate) for scenario in scenarios for rate in rates}
        keys = [(r['scenario'], r['target_rps']) for r in data['rows']]
        if len(keys) != len(expected) or set(keys) != expected:
            raise ValueError('Missing or duplicate measurement')
        for row in data['rows']:
            if row['vendor'] != vendor or row.get('batch') != 512 or row.get('trial') != 0:
                raise ValueError('Unexpected vendor or trial')
            if row['status'] not in ('measured', 'input_shortfall') or not row.get('operation_verified') or not (row.get('delivery_verified') or row.get('sampling_verified')) or row.get('output_batch_verified') is False:
                raise ValueError('Unverified measurement')
            if vendor == 'red' and row.get('binary_sha256') != data['binary_sha256']:
                raise ValueError('Rust binary differs from shard provenance')
        calibration = data['calibration']
        keys = [(c['scenario'], c['target_rps']) for c in calibration]
        if len(keys) != len(expected) or set(keys) != expected or not all(c['passed'] for c in calibration):
            raise ValueError('Missing, duplicate or failed calibration')
        calibrations.extend(dict(c, vendor=vendor) for c in calibration)
        rows.extend(data['rows'])
        for name, version in data['versions'].items():
            if name in versions and versions[name] != version:
                raise ValueError('Vendor versions differ')
            versions[name] = version
    return dict(first, vendors=VENDORS, rows=rows, calibration=calibrations, versions=versions,
                measured_at=max(d['measured_at'] for d in shards),
                execution_mode='parallel signal/vendor jobs; isolated agent/load/sink hosts; sequential scenarios and loads')


def package(root, output, commit):
    output.mkdir(parents=True, exist_ok=True)
    rust_hashes = set()
    for signal in ['metrics', 'traces']:
        matches = list(root.glob(f'*/{signal}.json'))
        if len(matches) == 1:
            data = json.loads(matches[0].read_text())
        else:
            data = merge_signal(matches, signal, commit)
        if data.get('profile') != 'full' or data.get('benchmark_commit') != commit:
            raise ValueError('Only complete full runs from the measured commit can be published')
        if len(data['rows']) != 60 or any(r['status'] not in ('measured', 'input_shortfall') for r in data['rows']):
            raise ValueError('Incomplete or invalid OTLP report')
        rust_hashes.add(data['binary_sha256'])
        (output / f'{signal}.json').write_text(json.dumps(data, indent=2) + '\n')
    if len(rust_hashes) != 1:
        raise ValueError('Signals used different Rust binaries')
    with tarfile.open(output / 'otlp-evidence.tar.gz', 'w:gz') as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(root)))
    assets = sorted(output.iterdir())
    (output / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in assets))


def publish(output, repo, commit, tag):
    notes = output / 'NOTES.md'
    notes.write_text('Daily metrics and trace ladders. Both signals use isolated agent/load/sink hosts and the same verified Rust candidate. Measured load shortfalls remain in the data. The archive includes all configs, raw results and agent logs.\n')
    existing = gh_release.find_release(gh, repo, tag)
    if existing and not existing['draft']:
        raise ValueError(f'OTLP release {tag} already published; evidence is immutable')
    if existing:
        gh_release.delete_release(gh, repo, existing['id'])
    release = gh_release.create_draft(gh, repo, tag, commit, f'OTLP Benchmark Report - {tag}', notes)
    assets = sorted(p for p in output.iterdir() if p.name != 'NOTES.md')
    gh_release.upload_assets(gh, repo, release['id'], assets)
    remote = gh_release.remote_digests(gh, repo, release['id'])
    expected = {p.name: 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}
    if remote != expected:
        raise ValueError('Uploaded evidence checksum mismatch; draft retained')
    gh_release.mark_published(gh, repo, release['id'], make_latest=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--commit', required=True)
    p.add_argument('--tag', required=True)
    p.add_argument('--repo', required=True)
    p.add_argument('--publish', action='store_true')
    p.add_argument('--profile', choices=['full', 'short'], default='full')
    a = p.parse_args()
    if a.profile == 'short':
        for signal in ['metrics', 'traces']:
            merge_signal(list(a.root.glob(f'*/{signal}.json')), signal, a.commit, 'short')
        print('All six short-run vendor shards verified')
        return
    package(a.root, a.output, a.commit)
    if a.publish:
        publish(a.output, a.repo, a.commit, a.tag)


if __name__ == '__main__':
    main()
