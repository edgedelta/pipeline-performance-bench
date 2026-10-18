import json,shutil,hashlib
from pathlib import Path
from otlpbench.scenario_chart import HTML
root=Path(__file__).resolve().parent; dest=root
runs=[]
for directory,name,label in [('', 'Saved Rust baseline','2e709b3'),('shared-ids','Inline trace identifiers','8c29318')]:
 rows=[];calibrations=[]
 for scenario in ['filter','sample']:
  p=root/directory/scenario/'results.json'
  if p.exists():
   data=json.loads(p.read_text());rows.extend(dict(r,scenario=scenario) for r in data['rows']);calibrations.extend(dict(c,scenario=scenario) for c in data['calibration'])
 if rows:runs.append(dict(name=name,red_label=label,seconds=60,rows=rows,calibration=calibrations,note='OTLP/gRPC input; uncompressed OTLP/HTTP output. Filter removes 25% of spans. Sample uses native 50% trace-ID sampling.'))
report=dict(signal='traces',runs=runs)
html=HTML.replace('Metrics scenario benchmarks','Trace Filter and Sample benchmarks').replace('METRICS','TRACES').replace('10,000 requests/sec × 512 points/request = 5.12 million points/sec','8,000 requests/sec × 512 spans/request = 4.096 million spans/sec').replace('Points/sec','Spans/sec').replace('points/sec','spans/sec').replace('Input points','Input spans').replace('Output points','Output spans')
html=html.replace("['pass-through','filter','enrich','aggregate','rollup','combined']","['filter','sample']")
html=html.replace('r.through_delivery.cpu_seconds/r.input_window.elapsed_seconds','r.through_delivery.cpu_seconds/r.load.seconds')
html=html.replace('r&&r.load&&r.delivery_verified&&r.operation_verified','r&&r.load&&r.operation_verified&&(r.delivery_verified||(r.scenario===\'sample\'&&r.sampling_verified))&&r.output_batch_verified!==false')
html=html.replace('normalized to the input window','divided by the 60-second offered-load window').replace('Aggregation and rollup use native processing and flush behavior.','Sample checks retention and matching parent/child fingerprints; it does not independently prove the exact retained set or rule out small delivery loss.')
html=html.replace('64 recurring resource groups × 64 host series.','256 complete two-span traces per request, with unique trace IDs across requests and stable resource metadata.').replace("${valid(r)?'Verified':'Not verified'}","${valid(r)?(r.scenario==='sample'?'Sampling checks':'Verified'):'Not verified'}")
html=html.replace('Every measured trial is listed below','Every measured trial is listed in the table').replace('<th>CPU cost</th>','<th>CPU cores</th>')
html=html.replace('__DATA__',json.dumps(report).replace('<','\\u003c'))
(dest/'index.html').write_text(html);(dest/'results.json').write_text(json.dumps(report,indent=2)+'\n')
print(dest)
