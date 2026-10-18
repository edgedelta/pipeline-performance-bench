import json
from pathlib import Path
from otlpbench.scenario_chart import HTML
root=Path('/tmp/mask-tail-optimization');out=Path('/tmp/otlp-visual/rps/mask-tail');out.mkdir(parents=True,exist_ok=True)
runs=[]
for directory,label,commit in [('', 'Saved baseline', '8c29318'),('candidate','Native fields','5f7da6c'),('final','Bounded Tail flush','326caf6'),('progress','Cooperative Tail','b200868')]:
 for rate in [1000,8000]:
  rows=[]
  for scenario in ['mask','tail']:
   p=root/directory/scenario/'results.json'
   if p.exists():rows.extend(dict(r,scenario=scenario) for r in json.loads(p.read_text())['rows'] if r['target_rps']==rate)
  if directory in ('final','progress') and not rows:continue
  if directory in ('final','progress'):
   for scenario in ['mask','tail']:
    p=root/'candidate'/scenario/'results.json'
    if p.exists():rows.extend(dict(r,scenario=scenario) for r in json.loads(p.read_text())['rows'] if r['target_rps']==rate and r['vendor']!='red')
  if rows:runs.append(dict(name=f'{label} · {rate:,} req/sec',red_label=commit,seconds=60,rows=rows,note=f'{rate:,} requests/sec × 512 spans/request. OTLP/gRPC input; uncompressed OTLP/HTTP output. Mask changes the secret attribute; Tail keeps error traces after a 1-second decision window. Follow-up Rust rows reuse the same-host OTel/Bindplane reference trials from the preceding iteration.'))
html=HTML.replace('Metrics scenario benchmarks','Trace Mask and Tail benchmarks').replace('METRICS','TRACES').replace('10,000 requests/sec × 512 points/request = 5.12 million points/sec','512 spans/request · compare 1k and 8k requests/sec').replace('Points/sec','Spans/sec').replace('points/sec','spans/sec').replace('Input points','Input spans').replace('Output points','Output spans')
html=html.replace('Output points','Output spans').replace('CPU seconds per input-window second','CPU seconds per offered-load second')
html=html.replace("['pass-through','filter','enrich','aggregate','rollup','combined']","['mask','tail']").replace('r.through_delivery.cpu_seconds/r.input_window.elapsed_seconds','r.through_delivery.cpu_seconds/r.load.seconds')
html=html.replace('r&&r.load&&r.delivery_verified&&r.operation_verified','r&&r.load&&r.delivery_verified&&r.operation_verified&&r.output_batch_verified!==false')
html=html.replace('normalized to the input window','divided by the 60-second offered-load window').replace('Aggregation and rollup use native processing and flush behavior.','Mask requires exact delivery and 512-span output batches. Tail requires exact retained-span counts, payload checks and paired-span fingerprints; invalid results are excluded.').replace('64 recurring resource groups × 64 host series.','256 complete two-span traces per request; only the child has ERROR status in retained traces. Resource metadata is stable.')
report=dict(signal='traces',runs=runs)
(out/'index.html').write_text(html.replace('__DATA__',json.dumps(report).replace('<','\\u003c')));(out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
print([(r['name'],len(r['rows'])) for r in runs])
