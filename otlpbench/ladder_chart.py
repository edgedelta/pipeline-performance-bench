"""Render telemetry request-rate ladders without publishing the public site."""
import argparse
import json
from pathlib import Path

SCENARIOS = ['pass-through', 'filter', 'aggregate', 'rollup', 'combined']
TRACE_SCENARIOS = ['pass-through', 'filter', 'mask', 'sample', 'tail']
RATES = [1000, 2000, 4000, 8000]
VENDORS = ['red', 'otelcol', 'bindplane']


def collect(root, source_commit, binary_sha256, allow_partial=False, signal="metrics", rates=None):
    rates = list(RATES if rates is None else rates)
    if not rates or any(not isinstance(r, int) or r <= 0 for r in rates) or rates != sorted(set(rates)):
        raise ValueError('rates must be positive, unique and increasing')
    rows, calibrations = [], []
    scenarios = TRACE_SCENARIOS if signal == "traces" else SCENARIOS
    for scenario in scenarios:
        path = root / scenario / 'results.json'
        raw = json.loads(path.read_text()) if path.exists() else {'rows': [], 'calibration': []}
        if raw.get('signal', signal) != signal: raise ValueError('result signal differs from report')
        calibrations.extend(dict(c, scenario=scenario) for c in raw['calibration'])
        for rate in rates:
            for vendor in VENDORS:
                matches = [r for r in raw['rows'] if r['vendor'] == vendor and r['target_rps'] == rate and r['batch'] == 512]
                if len(matches) > 1:
                    raise ValueError(f'duplicate case: {scenario}/{rate}/{vendor}')
                if not matches:
                    if not allow_partial:
                        raise ValueError(f'missing case: {scenario}/{rate}/{vendor}')
                    row = dict(vendor=vendor, target_rps=rate, batch=512, trial=0, status='pending')
                else:
                    row = dict(matches[0])
                    if vendor == 'red' and row.get('binary_sha256') and row['binary_sha256'] != binary_sha256:
                        raise ValueError('Rust binary does not match report provenance')
                row['scenario'] = scenario
                rows.append(row)
    return dict(schema=signal+'-request-ladder-v1', signal=signal, scenarios=scenarios, rates=rates,
                vendors=VENDORS, batch=512, seconds=60, trials=1, source_commit=source_commit,
                binary_sha256=binary_sha256, rows=rows, calibration=calibrations)


HTML = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pipeline Performance Benchmarks · Metrics ladder</title>
<style>
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#101010;color:#e7e7e7;font:16px system-ui,-apple-system,sans-serif;padding:28px}main{max-width:1720px;margin:auto;padding:38px;background:#202020;border:1px solid #393939;border-radius:20px}header{display:flex;justify-content:space-between;gap:24px;align-items:center}h1{font-size:32px;margin:10px 0}p{color:#aaa;line-height:1.5}small{color:#aaa}.controls{display:flex;gap:18px;flex-wrap:wrap;margin:26px 0}.group{display:inline-flex;background:#101010;border:1px solid #404040;border-radius:12px;padding:4px;gap:3px}button,select{font:inherit;color:#ddd;background:#292929;border:1px solid #484848;border-radius:8px;padding:11px 16px;cursor:pointer}button{background:transparent;border:0}.group button[aria-pressed=true]{background:#393939;color:white}button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid #fff;outline-offset:3px}label{display:flex;gap:10px;align-items:center;color:#aaa}.legend{display:flex;gap:28px;flex-wrap:wrap;margin:25px 0}.dot{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:9px}.version{font-family:ui-monospace,monospace;font-size:13px;color:#aaa}.chart-wrap{overflow-x:auto}svg{width:100%;min-width:800px;height:auto}#caption{margin-bottom:8px}.note{padding:17px 20px;background:#292929;border-radius:10px;color:#bbb;line-height:1.6}.note strong{color:#eee}a{color:#c6d9ff}details{margin-top:24px}summary{cursor:pointer;color:#ddd;padding:10px 0}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:11px 10px;border-bottom:1px solid #393939}th{color:#aaa}footer{border-top:1px solid #393939;margin-top:28px;padding-top:20px;color:#aaa;display:flex;gap:20px;justify-content:space-between;flex-wrap:wrap}.table-wrap{overflow-x:auto}.status{color:#aaa;font-size:14px}@media(max-width:800px){body{padding:12px}main{padding:20px}header{align-items:flex-start;flex-direction:column}h1{font-size:26px}.controls{gap:12px}.group button{padding:10px}.legend{gap:15px}}
</style>
<main><header><div><small>LOCAL PREVIEW · METRICS · RUST GENERATOR</small><h1>Pipeline Performance Benchmarks</h1><p id="subtitle"></p></div><div class="group" aria-label="Chart layout"><button data-mode="tier" aria-pressed="true">By load</button><button data-mode="trend" aria-pressed="false">Trend</button></div></header>
<div class="controls"><div class="group" id="tiers" aria-label="Offered requests per second"></div><label><span class="sr">Measure</span><select id="measure" aria-label="Measure"><option value="efficiency">Points/sec per core</option><option value="memory_efficiency">Points/sec per MB</option><option value="cpu">CPU cores</option><option value="memory">Memory MB</option><option value="rate">Requests/sec reached</option><option value="points">Points/sec reached</option></select></label><label id="scenarioControl" hidden>Scenario <select id="scenario"></select></label></div>
<div class="legend" id="legend"></div><p id="caption"></p><div class="chart-wrap"><svg id="chart" viewBox="0 0 1500 530" role="img" aria-label="Metric scenario benchmark results"></svg></div><p id="status" class="status"></p>
<div class="note"><strong>Solid bars sustained the offered load. Dashed bars fell short; their labels show achieved requests/sec.</strong> N/A means no verified measurement. All tiers are tested independently. One 60-second trial per case; CPU includes processing through final delivery, normalized to the input window. Memory is final RSS, not peak usage. These are fixed-load comparisons, not maximum-capacity estimates.</div>
<p>Aggregate uses native behavior: Rust reduces over 10-second windows; OTel and Bindplane reduce labels within each batch. Rollup and Combined use 60-second intervals, with native window boundaries and output volumes. Combined means cardinality reduction plus rollup. The fixture has one metric per 512-point request.</p>
<details><summary>Measured trials and verification</summary><div class="table-wrap"><table><thead><tr><th>Scenario</th><th>Offered req/s</th><th>Vendor</th><th>Reached req/s</th><th>CPU cores</th><th>Final RSS MB</th><th>Delivery / operation</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table></div></details>
<footer><span id="provenance"></span><a href="results.json">Download results</a></footer></main>
<script>
const data=__DATA__;
const names={red:'Edge Delta (Rust)',otelcol:'OpenTelemetry Collector',bindplane:'Bindplane (Dynatrace)'};
const colors={red:'#00cc66',otelcol:'#a348ff',bindplane:'#f04444'};
const labels={'pass-through':'Pass-Through',filter:'Filter',aggregate:'Aggregate',rollup:'Rollup',combined:'Combined',mask:'Mask',sample:'Sample',tail:'Tail'};
const versions={red:'PR #21 · '+data.source_commit.slice(0,7),otelcol:'0.162.0',bindplane:'1.110.1'};
let mode='tier',rate=Math.max(...data.rates),metric='efficiency',scenario='pass-through';
const el=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat('en-US',{notation:n>=10000?'compact':'standard',maximumFractionDigits:2}).format(n);
const shortRate=n=>n<1000?fmt(n):(n/1000).toFixed(2).replace(/\.00$/,'')+'k';
const valid=r=>!!(r&&r.load&&r.through_delivery&&r.operation_verified&&(r.delivery_verified||r.scenario==='sample'&&r.sampling_verified)&&r.output_batch_verified!==false);
const cpu=r=>r.through_delivery.cpu_seconds/(data.signal==='traces'?r.load.seconds:r.input_window.elapsed_seconds);
const lookup=(s,t,v)=>data.rows.find(r=>r.scenario===s&&r.target_rps===t&&r.vendor===v);
function value(r){if(!valid(r))return null;const points=r.load.achieved_rps*r.batch;switch(metric){case'cpu':return cpu(r);case'memory':return r.through_delivery.rss_mb;case'rate':return r.load.achieved_rps;case'points':return points;case'memory_efficiency':return r.through_delivery.rss_mb>0?points/r.through_delivery.rss_mb:null;default:return cpu(r)>0?points/cpu(r):null}}
const captions={efficiency:'Input points/sec per CPU core · higher is better',memory_efficiency:'Input points/sec per MB of final RSS · higher is better',cpu:'CPU seconds per input-window second · lower is better',memory:'Final resident memory, MB · lower is better',rate:'Requests/sec reached · higher is better',points:'Input points/sec reached · higher is better'};
function render(){
 document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
 el('tiers').hidden=mode==='trend';el('scenarioControl').hidden=mode!=='trend';
 document.querySelectorAll('[data-rate]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.rate===rate)));
 el('subtitle').textContent=mode==='tier'?`${fmt(rate)} requests/sec × 512 points/request = ${fmt(rate*512)} points/sec offered · OTLP/gRPC input`:`${labels[scenario]} · ${data.rates.map(shortRate).join(' → ')} requests/sec · 512 points/request · OTLP/gRPC input`;
 el('caption').textContent=captions[metric];
 const groups=mode==='tier'?data.scenarios:data.rates;
 const selected=groups.flatMap(g=>data.vendors.map(v=>lookup(mode==='tier'?g:scenario,mode==='tier'?rate:g,v)));
 const values=selected.map(value).filter(n=>n!==null&&Number.isFinite(n));
 const offered=metric==='rate'?(mode==='tier'?rate:Math.max(...data.rates)):metric==='points'?(mode==='tier'?rate:Math.max(...data.rates))*512:0;
 const max=Math.max(1,offered,...values)*1.18;
 let svg='<title>'+captions[metric]+'</title>';
 for(let i=0;i<=4;i++){const y=420-i*90;svg+=`<line x1="90" x2="1490" y1="${y}" y2="${y}" stroke="#393939"/><text x="76" y="${y+5}" text-anchor="end" fill="#aaa" font-size="14">${fmt(max*i/4)}</text>`}
 groups.forEach((g,i)=>{const width=1380/groups.length,base=100+i*width+(width-174)/2;data.vendors.forEach((v,j)=>{const r=lookup(mode==='tier'?g:scenario,mode==='tier'?rate:g,v),n=value(r),ok=n!==null&&Number.isFinite(n),solid=ok&&r.status==='measured',x=base+j*58,h=ok?n/max*360:0;svg+=`<g><title>${names[v]} · ${ok?fmt(n):'N/A'} · ${r?r.status.replaceAll('_',' '):'pending'}</title><rect x="${x}" y="${420-h}" width="46" height="${h}" rx="4" fill="${colors[v]}" fill-opacity="${solid?1:.25}" stroke="${colors[v]}" ${solid?'':'stroke-dasharray="5 4"'}/><text x="${x+23}" y="${405-h}" text-anchor="middle" fill="#ddd" font-size="12">${ok?fmt(n):r&&r.status==='pending'?'Pending':'N/A'}</text>${ok&&!solid?`<text x="${x+23}" y="442" text-anchor="middle" fill="#bbb" font-size="10">${shortRate(r.load.achieved_rps)} req/s</text>`:''}</g>`});svg+=`<text x="${base+81}" y="477" text-anchor="middle" fill="#ddd" font-size="17">${mode==='tier'?labels[g]:shortRate(g)+' req/s'}</text>`});
 el('chart').innerHTML=svg;
 const completed=data.rows.filter(r=>r.status!=='pending').length,verified=data.rows.filter(valid).length,shortfalls=data.rows.filter(r=>r.status==='input_shortfall').length;
 el('status').textContent=`${completed}/${data.rows.length} cases completed · ${verified} verified · ${shortfalls} load shortfalls${completed<data.rows.length?' · Run in progress; reload for new results.':''}`;
 const shown=data.rows.filter(r=>mode==='tier'?r.target_rps===rate:r.scenario===scenario);
 el('rows').innerHTML=shown.map(r=>`<tr><td>${labels[r.scenario]}</td><td>${fmt(r.target_rps)}</td><td>${names[r.vendor]}</td><td>${r.load?fmt(r.load.achieved_rps):'—'}</td><td>${r.through_delivery?cpu(r).toFixed(3):'—'}</td><td>${r.through_delivery?fmt(r.through_delivery.rss_mb):'—'}</td><td>${valid(r)?r.scenario==='sample'?'Sampling checks':'Verified':'Not verified'}</td><td>${r.status.replaceAll('_',' ')}</td></tr>`).join('');
}
el('legend').innerHTML=data.vendors.map(v=>`<span><i class="dot" style="background:${colors[v]}"></i>${names[v]} <span class="version">${versions[v]}</span></span>`).join('');
el('tiers').innerHTML=data.rates.map(r=>`<button data-rate="${r}" aria-pressed="${r===rate}">${shortRate(r)} req/s</button>`).join('');
el('scenario').innerHTML=data.scenarios.map(s=>`<option value="${s}">${labels[s]}</option>`).join('');
el('provenance').textContent='512 points/request · 64 connections · c8i.8xlarge · Rust '+data.source_commit.slice(0,7)+' · OTLP/HTTP output';
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;render()});
document.querySelectorAll('[data-rate]').forEach(b=>b.onclick=()=>{rate=+b.dataset.rate;render()});
el('measure').onchange=()=>{metric=el('measure').value;render()};el('scenario').onchange=()=>{scenario=el('scenario').value;render()};render();
</script></html>'''


def render(data):
    html = HTML
    if data.get('signal') == 'traces':
        start = html.index('<p>Aggregate uses native behavior:')
        end = html.index('</p>', start) + 4
        html = html[:start] + '<p>512 spans/request form 256 complete two-span traces. Trace IDs are unique across requests. Filter drops health traces (25%); Mask replaces the secret attribute; Sample retains approximately 50% by trace ID; Tail retains error traces (25%) after a 1-second decision window, with a 4-million-trace buffer. Collectors batch Tail output on a 500ms timer; Rust uses native decision flushing, including ingestion-assisted decisions in the latest build. Actual Tail batch sizes remain native. Resource metadata is stable across requests. Sample checks retention and matching parent/child fingerprints; it does not independently prove the exact vendor-specific retained set or rule out small delivery loss. Other scenarios verify exact output counts. Enrich is excluded.</p>' + html[end:]
        html = html.replace('METRICS', 'TRACES').replace('Metrics ladder', 'Traces ladder').replace('Metric scenario', 'Trace scenario')
        html = html.replace('normalized to the input window', 'divided by the 60-second offered-load window, including any final request and delivery drain')
        html = html.replace('CPU seconds per input-window second', 'CPU seconds per offered-load second')
        html = html.replace('Points/sec', 'Spans/sec').replace('points/sec', 'spans/sec').replace('points/request', 'spans/request')
    return html.replace('__DATA__', json.dumps(data).replace('<', '\\u003c'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--signal', choices=['metrics','traces'], default='metrics')
    parser.add_argument('--rates', help='Comma-separated positive request rates, in increasing order')
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    data = collect(args.results, args.source_commit, args.binary_sha256, args.allow_partial, args.signal, None if args.rates is None else [int(r) for r in args.rates.split(',')])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'results.json').write_text(json.dumps(data, indent=2) + '\n')
    (args.output / 'index.html').write_text(render(data))


if __name__ == '__main__':
    main()
