#!/usr/bin/env python3
"""Run on Linux: separate receiver, equal disjoint CPU sets, alternating generators.
No AWS calls; no release publishing. Each raw result is retained.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import urllib.request
from fixed import phase, attainment

ROOT = Path(__file__).resolve().parents[1]
LABELS={'go':'Go workers','rust':'Rust workers','rust_tasks':'Rust tasks + semaphore'}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def stats():
    with urllib.request.urlopen('http://127.0.0.1:18080/stats', timeout=2) as response:
        return json.load(response)

def efficiency(metrics):
    ack = metrics['acknowledged_logs_per_second']
    cpu = metrics['generator_cpu_percent']
    rss = metrics['generator_avg_memory_mb']
    return dict(cpu_microseconds_per_ack=cpu*10000/ack if ack and cpu is not None else None,
                logs_per_second_per_mb=ack/rss if rss else None)

def summarize(rows, generators=None):
    generators = generators or (['go', 'rust', 'rust_tasks'] if any(r['generator']=='rust_tasks' for r in rows) else ['go', 'rust'])
    result = []
    for rate in sorted({r['target'] for r in rows}):
        for name in generators:
            group = [r for r in rows if r['target'] == rate and r['generator'] == name]
            valid = [r for r in group if r['status'] != 'invalid']
            entry = dict(target=rate, generator=name, trials=len(group), valid_trials=len(valid), sustained_trials=sum(r.get('sustains_target', False) for r in valid))
            for key in ['offered_logs_per_second', 'acknowledged_logs_per_second', 'generator_cpu_percent', 'generator_avg_memory_mb', 'generator_peak_memory_mb', 'cpu_microseconds_per_ack', 'logs_per_second_per_mb', 'receiver_cpu_percent']:
                values = [r[key] for r in valid if r.get(key) is not None]
                entry[key] = statistics.median(values) if values else None
            entry['errors'] = sum(r.get('errors', 0) for r in valid)
            result.append(entry)
    return result

def render(data):
    m = data['environment']
    count = len(data['trials'])
    completion = 'COMPLETE' if data.get('complete') else ('FINISHED WITH INVALID TRIALS' if count == data.get('expected_trials') else f"INCOMPLETE: {count}/{data.get('expected_trials', '?')} trials recorded")
    lines = ['# Load generator comparison — local measured results', '',
        'Real local measurements against a common acknowledgment receiver; **not agent throughput results or AWS measurements**.', '', f'Run status: **{completion}**.', '',
        f"Linux {m['architecture']}; {m['logical_cpus']} VM vCPUs; {m['memory_bytes']/1e9:.2f} GB VM RAM; kernel `{m['kernel']}`.",
        f"Receiver CPU affinity: {m['receiver_cpus']}; generator CPU affinity: {m['generator_cpus']}. Both share this VM, on disjoint CPU sets. CPU frequency/physical-core mapping is controlled by the host, not pinned.",
        f"Each generator: a {data['workers']}-request HTTP concurrency limit, one corpus log per request, global offered-rate limit, {data['warmup_seconds']}s warm-up + {data['measurement_seconds']}s measurement, {data['repeats']} repeats. Balanced rotating execution order for three implementations (alternating for two); fresh receiver per trial. All configured tiers are attempted.", '',
        'CPU 100% = one logical core. Memory is process RSS, decimal MB (1,000,000 bytes), sampled each second; averages are time-weighted. CPU and RSS exclude the separate receiver. Receiver CPU below is measured across warm-up, measurement and HTTP drain. Other metrics cover only the measurement window.', '',
        'Sustained means offered within ±2% of target, acknowledged ≥98% of target and offered, and zero final errors/backpressure. A shortfall is a limit of this generator/receiver/VM setup; it does not establish an agent or language capacity ceiling. HTTP acknowledgments do not verify durable delivery.', '',
        f"Dispatch: Go and Rust worker pools each have {data['workers']} workers and {data['workers']} pending queue slots. The optional Rust task mode has a separate HTTP semaphore and {data.get('task_pending_capacity',data['workers'])} additional admission slots; it reuses idle connections.", '',
        'Medians across valid trials; sustained counts and errors cover all repeats. CPU/log normalizes unequal achieved rates; lower absolute resource usage alone is not an equal-throughput win.', '',
        '| Target logs/s | Generator | Offered logs/s | Ack logs/s | CPU % ↓ | Avg RSS MB ↓ | Peak RSS MB ↓ | CPU µs/ack ↓ | Ack logs/s/MB ↑ | Sustained trials | Errors | Receiver CPU % |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|']
    for r in data['summary']:
        def f(k, digits=1):
            return f"{r[k]:,.{digits}f}" if r.get(k) is not None else 'N/A'
        lines.append(f"| {r['target']:,} | {LABELS.get(r['generator'],r['generator'])} | {f('offered_logs_per_second',0)} | {f('acknowledged_logs_per_second',0)} | {f('generator_cpu_percent')} | {f('generator_avg_memory_mb')} | {f('generator_peak_memory_mb')} | {f('cpu_microseconds_per_ack',2)} | {f('logs_per_second_per_mb',0)} | {r['sustained_trials']}/{r['trials']} | {r['errors']} | {f('receiver_cpu_percent')} |")
    lines += ['', 'Invalid trials: '+str(sum(r['status']=='invalid' for r in data['trials']))+'. Each trial, policy, binary/source hashes, receiver counters and calculation inputs are retained in `data.json` and the adjacent raw JSON files.', '',
        'The receiver discards fully read HTTP bodies and returns 200. It performs no agent parsing, transforms or durable storage. All use the same payload bytes and request policy; HTTP stacks, runtime scheduling and User-Agent headers differ. No generator uses TLS or request batching in this comparison.', '']
    return '\n'.join(lines)

def render_brief(data):
    lines=['# Three-way load generator comparison' if len(data.get('generators',[]))==3 else '# Load generator comparison', '',
           'Real local Linux generator measurements against the same external HTTP acknowledgment receiver. These are not agent benchmarks or AWS results.', '',
           f"{data['workers']} maximum concurrent HTTP requests, {data['workers']} worker-queue slots / {data.get('task_pending_capacity',data['workers'])} additional task-admission slots. Four generator CPUs and four separate receiver CPUs when run with the default `--cores 4`. Actual CPU sets and environment are recorded in [data.json](data.json).", '',
           f"{data['warmup_seconds']}s warm-up + {data['measurement_seconds']}s measurement, {data['repeats']} repeats per configuration, balanced rotating order. Medians of valid trials only.", '',
           '| Target logs/sec | Implementation | Ack logs/sec | CPU cores | Avg RSS MB | Sustained/valid trials |',
           '|---:|---|---:|---:|---:|---:|']
    for r in sorted(data['summary'],key=lambda r:(-r['target'],list(LABELS).index(r['generator']))):
        def value(k,scale=1,digits=1):
            return f"{r[k]/scale:,.{digits}f}" if r.get(k) is not None else 'N/A'
        lines.append(f"| {r['target']:,} | {LABELS[r['generator']]} | {value('acknowledged_logs_per_second',digits=0)} | {value('generator_cpu_percent',100,2)} | {value('generator_avg_memory_mb')} | {r['sustained_trials']}/{r['valid_trials']} |")
    invalid=[r for r in data['trials'] if r['status']=='invalid']
    lines += ['',f"Recorded {len(data['trials'])}/{data.get('expected_trials','?')} trials; {len(invalid)} invalid and excluded. "+('Complete valid collection.' if data.get('complete') else 'This is not a complete valid collection.'), '',
              'CPU cores = process CPU % / 100. RSS is generator process memory in decimal MB (1,000,000 bytes); receiver resources are excluded. Sustained means offered within ±2% of target, acknowledged ≥98% of target and offered rate, and zero final errors/backpressure. Under-target results are not equal-throughput wins. HTTP acknowledgment does not verify durable delivery.', '',
              'The worker counts and task semaphore limits bound logical concurrency, not OS threads. These implementations run sequentially on the same CPU allocation. A task-per-request design does not imply a higher rate; consult the measurements.', '',
              '[Detailed offered rates, CPU/log, throughput/MB and receiver measurements](report.md) · [Every trial and raw result filenames](data.json)', '']
    return '\n'.join(lines)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--go', required=True); p.add_argument('--rust', required=True); p.add_argument('--receiver', required=True)
    p.add_argument('--out', required=True); p.add_argument('--rates', default='25000,75000,100000,200000')
    p.add_argument('--seconds', type=int, default=15); p.add_argument('--warmup', type=int, default=2); p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--workers', type=int, default=256); p.add_argument('--cores', type=int, default=4)
    p.add_argument('--include-tasks', action='store_true', help='Compare Go workers, Rust workers and Rust task-per-request dispatch')
    p.add_argument('--task-pending-capacity', type=int, help='Additional bounded admitted tasks; default matches worker queue size')
    args=p.parse_args()
    generators=['go','rust','rust_tasks'] if args.include_tasks else ['go','rust']
    task_pending=args.workers if args.task_pending_capacity is None else args.task_pending_capacity
    if task_pending<0: p.error('pending capacity must be nonnegative')
    if min(args.seconds,args.warmup,args.repeats,args.workers,args.cores) < 1: p.error('positive durations, repeats, workers and cores required')
    rates=[int(r) for r in args.rates.split(',')]
    if any(r<1 for r in rates): p.error('positive rates required')
    cpus=sorted(os.sched_getaffinity(0))
    if len(cpus)<args.cores*2: p.error('need disjoint CPU sets for receiver and generator')
    receiver_cpus=cpus[:args.cores]; generator_cpus=cpus[args.cores:2*args.cores]
    out=Path(args.out).resolve(); out.mkdir(parents=True,exist_ok=False)
    payload=ROOT/'payloads/fixed-nginx.ndjson'
    env=dict(os.environ,GOMAXPROCS=str(args.cores))
    mem=int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemTotal:')).split()[1])*1024
    data=dict(schema_version=1, synthetic=False, complete=False, started_utc=datetime.now(timezone.utc).isoformat(), rates=rates, expected_trials=len(rates)*len(generators)*args.repeats, generators=generators, task_pending_capacity=task_pending, environment=dict(architecture=platform.machine(),kernel=platform.release(),logical_cpus=os.cpu_count(),memory_bytes=mem,receiver_cpus=receiver_cpus,generator_cpus=generator_cpus), workers=args.workers,measurement_seconds=args.seconds,warmup_seconds=args.warmup,repeats=args.repeats,payload_sha256=digest(payload),binaries={k:dict(sha256=digest(getattr(args,k))) for k in ['go','rust','receiver']},source_sha256={str(p.relative_to(ROOT)):digest(p) for p in [ROOT/'loadgen-rust/Cargo.toml', ROOT/'loadgen-rust/Cargo.lock', ROOT/'loadgen-rust/src/main.rs', ROOT/'tools/compare_loadgens.py', ROOT/'tools/loadgen_receiver/main.go', ROOT/'tools/fixed.py']},trials=[])
    for repeat in range(args.repeats):
        for rate in rates:
            for name in (generators[repeat%len(generators):]+generators[:repeat%len(generators)]):
                stem=f'{rate}-{repeat+1}-{name}'
                with (out/f'{stem}.receiver.log').open('w') as log:
                    receiver=subprocess.Popen([str(Path(args.receiver).resolve())],env=env,stdout=log,stderr=log,preexec_fn=lambda:os.sched_setaffinity(0,receiver_cpus))
                    try:
                        for attempt in range(100):
                            if receiver.poll() is not None: raise RuntimeError('receiver exited')
                            try: before=stats(); break
                            except OSError: time.sleep(.05)
                        else: raise RuntimeError('receiver never ready')
                        command=[str(Path(args.rust if name.startswith('rust') else args.go).resolve()),'--endpoint','http://127.0.0.1:18080/ingest','--number','1','--workers',str(args.workers),'--timeout','30s','--max-retries','2','--retry-ambiguous','--fixed-rate',str(rate),'--fixed-warmup',f'{args.warmup}s','--total-time',f'{args.seconds}s','--fixed-payload-file',str(payload),'--fixed-output',str(out/f'{stem}.json')]
                        if name.startswith('rust'): command+=['--runtime-threads',str(args.cores)]
                        if name=='rust_tasks': command+=['--dispatch-mode','tasks','--max-inflight',str(args.workers),'--pending-capacity',str(task_pending)]
                        with (out/f'{stem}.generator.log').open('w') as genlog:
                            subprocess.run(command,check=True,env=env,stdout=genlog,stderr=genlog,timeout=args.seconds+args.warmup+70,preexec_fn=lambda:os.sched_setaffinity(0,generator_cpus))
                        after=stats()
                        row=dict(target=rate,generator=name,repeat=repeat+1,command=command,raw_file=f'{stem}.json',receiver_before=before,receiver_after=after)
                        try:
                            raw=json.loads((out/f'{stem}.json').read_text())
                            assert raw['payload_sha256']==data['payload_sha256'], 'payload mismatch'
                            expected_policy=dict(schema_version=2,target_logs_per_second=rate,workers=None if name=='rust_tasks' else args.workers,configured_measurement_seconds=args.seconds,warmup_seconds=args.warmup,request_timeout_seconds=30,max_retries=2,retry_ambiguous=True,calibration=False)
                            assert all(raw.get(k)==v for k,v in expected_policy.items()), 'workload/delivery policy mismatch'
                            assert raw['measurement']['scheduled_logs']==rate*args.seconds, 'global rate budget mismatch'
                            if name=='rust_tasks':
                                assert raw['dispatch_mode']=='tasks' and raw['max_inflight']==args.workers and raw['pending_capacity']==task_pending, 'task limits mismatch'
                                for part in ['warmup','measurement']:
                                    assert raw[part]['peak_admitted_tasks']<=args.workers+task_pending, 'unbounded tasks'
                                    assert raw[part]['admission_dropped_logs']==raw[part]['worker_queue_dropped_logs'], 'admission accounting mismatch'
                            metrics=phase(raw,args.seconds,require_agent=False)
                            phase(dict(raw,measurement=raw['warmup']),args.warmup,require_agent=False)
                            expected=sum(raw[k]['acknowledged_logs']+raw[k]['acknowledged_after_window'] for k in ['warmup','measurement'])
                            assert after['requests']-before['requests']==expected, 'receiver acknowledgment count mismatch'
                            row.update(metrics,status='measured',sustains_target=attainment(metrics,rate))
                            row.update(efficiency(metrics))
                            row.update(receiver_cpu_percent=(after['cpu_usec']-before['cpu_usec'])/(after['unix_seconds']-before['unix_seconds'])/10000)
                        except (ValueError,KeyError,AssertionError) as e: row.update(status='invalid',reason=str(e))
                        data['trials'].append(row); data['summary']=summarize(data['trials'],generators)
                        data['complete']=len(data['trials'])==data['expected_trials'] and all(r['status']!='invalid' for r in data['trials'])
                        (out/'data.json').write_text(json.dumps(data,indent=2)+'\n'); (out/'report.md').write_text(render(data))
                        (out/'summary.md').write_text(render_brief(data))
                        if row['status']=='invalid':
                            print(stem, 'invalid:', row['reason'], flush=True)
                        else:
                            print(stem,row['status'],round(row['acknowledged_logs_per_second']),f"CPU {row['generator_cpu_percent']:.1f}%",flush=True)
                    finally:
                        receiver.terminate()
                        try: receiver.wait(timeout=5)
                        except subprocess.TimeoutExpired: receiver.kill(); receiver.wait()
                time.sleep(.5)
    if any(r['status']=='invalid' for r in data['trials']): raise SystemExit('Invalid trials: inspect report; do not treat as complete valid comparison')

if __name__=='__main__': main()
