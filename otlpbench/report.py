"""Render PR-only evidence; never writes releases or the public Pages dataset."""
import argparse
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
    lines += ['', '## Forwarding at 10k input items/sec', '', '| Agent | Metrics CPU cores | Metrics RSS MB | Traces CPU cores | Traces RSS MB |', '|---|---:|---:|---:|---:|']
    for vendor,name in VENDORS.items():
        cells=[]
        for signal in ('metrics','traces'):
            row=next((r for r in datasets.get(vendor,{}).get('rows',[]) if r['signal']==signal and r['scenario']=='pass-through'),{})
            m=next((m for m in row.get('measurements',[]) if m['rate']==10000 and m['status']=='measured'),{})
            cells += [f"{m[key]:.3f}" if isinstance(m.get(key),(int,float)) else '—' for key in ('cpu_cores','rss_mb')]
        lines.append('| '+name+' | '+' | '.join(cells)+' |')
    lines += ['', 'A dash means no validated measurement. These are fixed-load resource costs, not capacity rankings.', '', '## All scenarios', '', '| Signal | Scenario | Agent | Result | Accepted/s at 10k | CPU cores | RSS MB |', '|---|---|---|---|---:|---:|---:|']
    for signal, scenarios in SCENARIOS.items():
        for scenario in scenarios:
            for vendor,name in VENDORS.items():
                row=next((r for r in datasets.get(vendor,{}).get('rows',[]) if r['signal']==signal and r['scenario']==scenario),{})
                m=next((m for m in row.get('measurements',[]) if m['rate']==10000),{})
                def fmt(key):
                    v=m.get(key); return f'{v:,.2f}' if isinstance(v,(int,float)) else '—'
                lines.append(f"| {signal} | {LABELS.get(scenario,scenario.title())} | {name} | {m.get('status',row.get('status','not_run'))} | {fmt('accepted_per_second')} | {fmt('cpu_cores')} | {fmt('rss_mb')} |")
    lines += ['', '## Correctness and configuration evidence', '']
    for vendor,d in datasets.items():
        lines += [f"### {VENDORS[vendor]}", '', f"Commit: `{d['commit']}`. Binary SHA-256: `{d.get('binary_sha256','unavailable')}`.", '']
        for row in d['rows']:
            lines.append(f"- {row['signal']}/{row['scenario']}: **{row['status']}** — {row.get('detail','')}")
    lines += ['', 'Missing adapters (`not_configured`) are harness work remaining, not proof that a vendor cannot support the scenario. Raw configurations, correctness captures, calibration and measurements are in the accompanying evidence archive. Each result records its benchmark commit and binary hash. No release or public website is updated by this workflow.', '']
    return '\n'.join(lines)


if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('--output',default='otlp-preview.md'); a=ap.parse_args()
    text=render(a.root); Path(a.output).write_text(text)
    datasets=[json.loads(p.read_text()) for p in Path(a.root).rglob('results.json')]
    template=Path(__file__).with_name('preview.html').read_text()
    Path(a.output).with_suffix('.html').write_text(template.replace('__DATA__',json.dumps(datasets).replace('<',r'\u003c')))
