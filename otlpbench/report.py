"""Render PR-only evidence; never writes releases or the public Pages dataset."""
import argparse
import html
import json
from pathlib import Path
from .model import VENDORS, LABELS, SCENARIOS


def render(root):
    datasets={}
    for path in Path(root).rglob('results.json'):
        d=json.loads(path.read_text()); datasets[d['vendor']]=d
    lines=['# OTLP metrics and traces — PR preview', '', 'Exploratory fixed-rate run: 512 items/request, four persistent OTLP/gRPC clients, no compression. Native OTLP/HTTP output to a local destination. These are not maximum-capacity rankings. Correctness failures have no performance score.', '', '| Agent | Version |', '|---|---|']
    for vendor,name in VENDORS.items():
        d=datasets.get(vendor,{})
        lines.append(f"| {name} | {d.get('version','Not run').splitlines()[0]} |")
    lines += ['', '| Signal | Scenario | Agent | Result | Accepted/s at 10k | CPU cores | RSS MB |', '|---|---|---|---|---:|---:|---:|']
    for signal, scenarios in SCENARIOS.items():
        for scenario in scenarios:
            for vendor,name in VENDORS.items():
                row=next((r for r in datasets.get(vendor,{}).get('rows',[]) if r['signal']==signal and r['scenario']==scenario),{})
                m=next((m for m in row.get('measurements',[]) if m['rate']==10000),{})
                def fmt(key):
                    v=m.get(key); return f'{v:,.2f}' if isinstance(v,(int,float)) else '—'
                lines.append(f"| {signal} | {LABELS.get(scenario,scenario.title())} | {name} | {row.get('status','not_run')} | {fmt('accepted_per_second')} | {fmt('cpu_cores')} | {fmt('rss_mb')} |")
    lines += ['', '## Correctness and configuration evidence', '']
    for vendor,d in datasets.items():
        lines += [f"### {VENDORS[vendor]}", '', f"Commit: `{d['commit']}`. Binary SHA-256: `{d.get('binary_sha256','unavailable')}`.", '']
        for row in d['rows']:
            lines.append(f"- {row['signal']}/{row['scenario']}: **{row['status']}** — {row.get('detail','')}")
    lines += ['', 'Missing adapters (`not_configured`) are harness work remaining, not proof that a vendor cannot support the scenario. Raw configurations, logs, correctness captures, calibration and measurements are in the workflow artifacts. No release or public website is updated by this workflow.', '']
    return '\n'.join(lines)


if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('--output',default='otlp-preview.md'); a=ap.parse_args()
    text=render(a.root); Path(a.output).write_text(text)
    Path(a.output).with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><title>OTLP benchmark PR preview</title><style>body{font:14px monospace;background:#171717;color:#eee;padding:2em}pre{white-space:pre-wrap}</style><pre>'+html.escape(text)+'</pre>')
