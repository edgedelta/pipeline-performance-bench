"""Run and package the daily OTLP ladders on isolated hosts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from otlpbench.ladder_chart import collect, render, SCENARIOS, TRACE_SCENARIOS, VENDORS

RATES = {'metrics': [1000, 2000, 4000, 8000], 'traces': [100, 200, 300, 500]}


def report(root, output, signal, release, profile='full', vendor=None):
    rates = RATES[signal] if profile == 'full' else RATES[signal][:1]
    data = collect(root, release['source_commit'], release['binary_sha256'], signal=signal, rates=rates, vendors=[vendor] if vendor else None)
    data.update(seconds=60 if profile == 'full' else 10, profile=profile,
                measured_at=datetime.now(timezone.utc).isoformat(),
                benchmark_commit=os.environ.get('GITHUB_SHA', ''),
                run_url=os.environ.get('BENCHMARK_RUN_URL', ''), rust_release=release)
    data['versions'] = {'red': release['version'] + ' · ' + release['source_commit'][:7]}
    for vendor in set(data['vendors']) - {'red'}:
        versions = {r.get('version') for r in data['rows'] if r['vendor'] == vendor and r.get('version')}
        if len(versions) != 1:
            raise ValueError(f'{vendor}: missing or inconsistent versions')
        version = re.search(r'v?\d+\.\d+\.\d+', versions.pop())
        if not version:
            raise ValueError(f'{vendor}: unrecognized version')
        data['versions'][vendor] = version.group()
    output.mkdir(parents=True, exist_ok=True)
    (output / f'{signal}.json').write_text(json.dumps(data, indent=2) + '\n')
    (output / f'{signal}.html').write_text(render(data))
    if len(data['calibration']) != len(data['scenarios']) * len(rates) or not all(c['passed'] for c in data['calibration']):
        raise ValueError('Generator/sink calibration failed; evidence retained')
    invalid = [r for r in data['rows'] if r['status'] not in ('measured', 'input_shortfall') or not r.get('operation_verified') or not (r.get('delivery_verified') or r.get('sampling_verified')) or r.get('output_batch_verified') is False]
    if invalid:
        raise ValueError(f'{len(invalid)} invalid cases; evidence retained')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--signal', choices=RATES, required=True)
    p.add_argument('--vendor', choices=VENDORS)
    p.add_argument('--profile', choices=['full', 'short'], default='full')
    p.add_argument('--binaries', type=Path, default=Path('.loadgen-build'))
    p.add_argument('--output', type=Path, default=Path('otlp-daily-results'))
    a = p.parse_args()
    release = json.loads((a.binaries / 'release.json').read_text())
    if hashlib.sha256((a.binaries / 'red').read_bytes()).hexdigest() != release['binary_sha256']:
        raise ValueError('Rust binary does not match shared release provenance')
    raw = a.output / a.signal
    scenarios = TRACE_SCENARIOS if a.signal == 'traces' else SCENARIOS
    command = [sys.executable, '-u', '-m', 'otlpbench.cloud_rps', '--external-cleanup',
               '--red-binary', str(a.binaries / 'red'), '--traffic-binary', str(a.binaries / 'otlp-traffic'),
               '--output', str(raw), '--signal', a.signal, '--scenarios', ','.join(scenarios),
               '--vendors', a.vendor or ','.join(VENDORS), '--seconds', '60' if a.profile == 'full' else '10',
               '--rates', ','.join(map(str, RATES[a.signal] if a.profile == 'full' else RATES[a.signal][:1])),
               '--batches', '512', '--series-groups', '64' if a.signal == 'metrics' else '0',
               '--connections', '64', '--concurrency', '1024', '--trials', '1']
    subprocess.run(command, cwd=ROOT, check=True)
    data = report(raw, a.output, a.signal, release, a.profile, a.vendor)
    summary = f"{a.signal.title()}: {len(data['rows'])} verified cases, {sum(r['status']=='input_shortfall' for r in data['rows'])} load shortfalls. Rust {release['version']} ({release['source_commit'][:7]}).\n"
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(summary)


if __name__ == '__main__':
    main()
