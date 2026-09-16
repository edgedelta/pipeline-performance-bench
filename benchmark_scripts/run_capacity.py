#!/usr/bin/env python3
"""One Rust workload for fixed-rate resource tests and sustained-throughput search."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import capacity
import fixed
import run_fixed


def run(vendor, scenario):
    root = Path('benchmark_results'); root.mkdir(exist_ok=True)
    provenance = {'schema_version': 4, 'benchmark_profile': os.environ.get('BENCHMARK_PROFILE', 'full')}
    rates = fixed.rates_for(provenance)
    path = root/f'{vendor}_{scenario}.capacity.json'
    record = {'schema_version': 1, 'vendor': vendor, 'scenario': scenario, 'complete': False,
              'policy': capacity.policy(provenance), 'fixed_rates': rates, 'probe_rates': []}
    path.write_text(json.dumps(record, indent=2)+'\n')
    run_fixed.run(vendor, scenario)
    payload = hashlib.sha256(Path('fixed-nginx.ndjson').read_bytes()).hexdigest()
    outcomes = {r: fixed.tier(root,vendor,scenario,r,payload)['status'] for r in rates}
    if any(s not in fixed.REPORTABLE_STATUSES for s in outcomes.values()):
        raise RuntimeError('Invalid fixed-rate evidence')
    while (rate := capacity.next_probe(provenance, outcomes)) is not None:
        run_fixed.run(vendor, scenario, rates=[rate])
        outcome = fixed.tier(root,vendor,scenario,rate,payload)
        if outcome['status'] not in fixed.MEASURED_STATUSES: raise RuntimeError(outcome['reason'])
        record['probe_rates'].append(rate); outcomes[rate] = outcome['status']
    record['complete'] = True
    path.write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vendor', choices=run_fixed.SERVICES); parser.add_argument('scenario')
    args = parser.parse_args(); run(args.vendor, args.scenario)
