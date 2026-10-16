"""Render a standalone request-rate report without touching the public site."""
import json
from pathlib import Path
import sys

HTML = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pass-Through · Request-rate benchmark</title>
<style>*{box-sizing:border-box}body{background:#101010;color:#ddd;font:16px system-ui;margin:0;padding:36px}main{max-width:1500px;margin:auto;background:#202020;border:1px solid #383838;border-radius:20px;padding:36px}h1{margin:8px 0;font-size:32px}small,p{color:#aaa}.controls{display:flex;gap:24px;flex-wrap:wrap;margin:28px 0}select{background:#303030;color:white;border:1px solid #555;border-radius:8px;padding:10px;font:inherit}label{display:flex;align-items:center;gap:12px}.legend{display:flex;gap:30px;margin:24px 0}.dot{display:inline-block;width:13px;height:13px;border-radius:3px;margin-right:8px}svg{width:100%;height:auto;min-height:300px}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:12px;text-align:left;border-bottom:1px solid #363636}th{color:#aaa;font-weight:500}.note{padding:18px;background:#292929;border-radius:8px;line-height:1.6}a{color:#bbb}.footer{margin-top:24px;font-size:13px;color:#aaa}</style>
<main><small>LOCAL PREVIEW · PR #29 · RUST LOAD GENERATOR</small><h1>Pipeline Performance Benchmarks</h1><p>Metrics · Pass-Through · OTLP/gRPC input · separate load, agent, and sink hosts</p>
<div class="controls"><label>Points per request <select id="batch"></select></label><label>Offered requests/sec <select id="rate"></select></label><label>Trial <select id="trial"></select></label><label>View <select id="view"><option value="rps">Requests/sec reached</option><option value="points">Points/sec reached</option><option value="cpu">CPU cores</option></select></label></div>
<div class="legend"><span><i class="dot" style="background:#00cc66"></i>Edge Delta (Rust)</span><span><i class="dot" style="background:#a348ff"></i>OpenTelemetry Collector</span><span><i class="dot" style="background:#f04444"></i>Bindplane (Dynatrace)</span></div><p id="context"></p><svg id="chart" viewBox="0 0 1200 430" aria-label="Pass-Through results"></svg><div id="note" class="note"></div><table><thead><tr><th>Vendor</th><th>Requests/sec</th><th>Points/sec</th><th>CPU cores</th><th>Delivery</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table><div id="footer" class="footer">30 seconds per agent trial · 64 persistent connections · up to 1,024 in-flight requests · no compression. CPU includes the final delivery drain. Values are fixed-load measurements, not maximum-capacity claims. Harness-limited cases are unmeasured.</div></main>
<script>const data=__DATA__;const names={red:'Edge Delta (Rust)',otelcol:'OpenTelemetry Collector',bindplane:'Bindplane (Dynatrace)'},colors={red:'#00cc66',otelcol:'#a348ff',bindplane:'#f04444'};
const fmt=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:2,notation:n>=10000?'compact':'standard'}).format(n);
for(const [id,key] of [['batch','batch'],['rate','target_rps']]){document.getElementById(id).innerHTML=[...new Set(data.calibration.map(r=>r[key]))].sort((a,b)=>a-b).map(v=>`<option>${v}</option>`).join('')}
document.getElementById('trial').innerHTML=[...new Set(data.rows.map(r=>r.trial??0))].sort((a,b)=>a-b).map(v=>`<option value="${v}">${v+1}</option>`).join('');
document.getElementById('footer').textContent=`${data.seconds} seconds per agent trial · ${data.connections} persistent connections · up to ${data.concurrency.toLocaleString()} in-flight requests · no compression. CPU includes the final delivery drain. Fixed-load measurements, not maximum-capacity claims. Harness-limited cases are unmeasured.`;
function render(){const trial=+document.getElementById('trial').value,batch=+document.getElementById('batch').value,rate=+document.getElementById('rate').value,view=document.getElementById('view').value;
const rows=['red','otelcol','bindplane'].map(v=>data.rows.find(r=>r.vendor===v&&r.batch===batch&&r.target_rps===rate&&(r.trial===trial||!r.load))).filter(Boolean),c=data.calibration.find(r=>r.batch===batch&&r.target_rps===rate);
document.getElementById('context').textContent=`${fmt(rate)} requests/sec × ${batch} points/request = ${fmt(rate*batch)} points/sec offered`;
document.getElementById('note').textContent=c?.passed?`Harness calibration passed: ${fmt(c.achieved_rps)} requests/sec with verified point counts and sums. Dashed bars indicate a load or delivery shortfall.`:`Harness calibration did not pass: reached ${fmt(c?.achieved_rps||0)} of ${fmt(rate)} requests/sec. Agent results at this load are deliberately left unmeasured.`;
const value=r=>!r.load?0:view==='cpu'?r.through_delivery.cpu_cores:view==='points'?r.load.achieved_rps*batch:r.load.achieved_rps;
const max=Math.max(...rows.map(value),view==='rps'?rate:view==='points'?rate*batch:1)*1.15;
let s='';for(let i=0;i<=4;i++){const y=350-i*75;s+=`<line x1="90" x2="1160" y1="${y}" y2="${y}" stroke="#393939"/><text x="75" y="${y+5}" fill="#aaa" text-anchor="end" font-size="14">${fmt(max*i/4)}</text>`}
rows.forEach((r,i)=>{const x=180+i*350,v=value(r),h=v/max*300,color=colors[r.vendor],solid=r.status==='measured';s+=`<rect x="${x}" y="${350-h}" width="140" height="${h}" rx="5" fill="${color}" fill-opacity="${solid?1:.25}" stroke="${color}" ${solid?'':'stroke-dasharray="6 4"'}/><text x="${x+70}" y="${335-h}" text-anchor="middle" fill="#ddd">${r.load?fmt(v):'N/A'}</text><text x="${x+70}" y="390" text-anchor="middle" fill="#ddd">${names[r.vendor]}</text>`});document.getElementById('chart').innerHTML=s;
document.getElementById('rows').innerHTML=rows.map(r=>`<tr><td>${names[r.vendor]}${r.version?'<br><small>'+r.version.split('\\n')[0]+'</small>':''}</td><td>${r.load?fmt(r.load.achieved_rps):'—'}</td><td>${r.load?fmt(r.load.achieved_rps*batch):'—'}</td><td>${r.load?r.through_delivery.cpu_cores.toFixed(3):'—'}</td><td>${r.load?(r.delivery_verified?'Verified':'Mismatch'):'—'}</td><td>${r.status.replaceAll('_',' ')}</td></tr>`).join('')}
for(const el of document.querySelectorAll('select'))el.onchange=render;render();</script>'''


def main():
    data=json.loads(Path(sys.argv[1]).read_text())
    output=Path(sys.argv[2]);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(HTML.replace('__DATA__',json.dumps(data).replace('<','\\u003c')))


if __name__=='__main__':main()
