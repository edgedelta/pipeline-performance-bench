#!/usr/bin/env python3
"""Check short validation coverage/recovery without creating release checksums."""
import json
from pathlib import Path
import sys
from summarize import summarize
from fixed import REPORTABLE_STATUSES, rates_for


def validate(directory):
    directory = Path(directory)
    data = summarize(directory)
    provenance = data['provenance']
    if provenance.get('benchmark_profile') != 'short':
        raise ValueError('Expected short validation profile')
    vendors = list(provenance.get('shards', {}))
    if not vendors: raise ValueError('Missing validated agent shards')
    rows = []
    for vendor in vendors:
        if data['scenarios'][f'{vendor}/pass-through']['status'] not in ('ok', 'errors'):
            raise ValueError(f'{vendor}: missing legacy throughput smoke test')
        for rate in rates_for(provenance):
            t = data['fixed_throughput']['tiers'][f'{vendor}/pass-through/{rate}']
            if t['status'] not in REPORTABLE_STATUSES:
                raise ValueError(f'{vendor}/{rate}: {t["status"]}')
            if vendor == 'red' and (rate == 10000 and t['status'] != 'ok' or t.get('errors', 0)):
                raise ValueError(f'Rust recovery validation failed at {rate}: {t["reason"]}')
            rows.append(f'| {vendor} | {rate:,} | {t["status"]} | {t.get("errors", "N/A")} |')
    report = '# Short validation passed — not a full benchmark\n\nPass-through only; 10-second legacy throughput windows, 60-second fixed-rate measurements at 10k and 125k. Higher targets may be skipped after shortfall. Other agents may record genuine capacity shortfalls; Rust must pass 10k and have no final errors in measured fixed tiers. This does not validate other scenario pipelines or establish long-run reliability.\n\n| Agent | Target logs/sec | Outcome | Final errors |\n|---|---:|---|---:|\n' + '\n'.join(rows) + '\n'
    (directory/'short-validation.md').write_text(report)
    print(report)
    return data


if __name__ == '__main__': validate(Path(sys.argv[1]))
