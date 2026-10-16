"""Correctness-gated fixed-rate OTLP/gRPC preview on one isolated host."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import platform
import signal as signals
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import grpc
import psutil
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2_grpc import MetricsServiceStub
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import TraceServiceStub
from .configs import config
from .model import SCENARIOS, expected, fixture, records, validate


def sink(path='', capture=False):
    req = urllib.request.Request('http://127.0.0.1:14318/'+path, data=b'' if path else None)
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)


def stop(p):
    if p.poll() is None:
        os.killpg(p.pid, signals.SIGTERM)
        try: p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signals.SIGKILL); p.wait()


def ready(p, port):
    for _ in range(100):
        if p.poll() is not None: raise RuntimeError(f'agent exited: {p.returncode}')
        try:
            with socket.create_connection(('127.0.0.1',port), timeout=.2): return
        except OSError: time.sleep(.2)
    raise RuntimeError(f'port {port} did not become ready')


def client(signal, port):
    channel = grpc.insecure_channel(f'127.0.0.1:{port}', options=[('grpc.max_send_message_length',16*1024*1024)], compression=grpc.Compression.NoCompression)
    stub = MetricsServiceStub(channel) if signal == 'metrics' else TraceServiceStub(channel)
    return channel, stub.Export


def load(signal, port, rate, seconds, batch=512, sequence_offset=100000):
    start = time.monotonic()
    base = (int(time.time())//60-2)*60
    def worker(index):
        channel, export = client(signal, port)
        sent = rejected = errors = 0
        latency = []
        seq = index
        deadline = start + seconds
        while True:
            due = start + (seq+1)*batch/rate
            if (seq+1)*batch > int(rate*seconds): break
            time.sleep(max(0, due-time.monotonic()))
            if time.monotonic() >= deadline: break
            req = fixture(signal, batch, sequence=seq+sequence_offset, base=base)
            t = time.monotonic()
            try:
                response = export(req, timeout=5)
                n = response.partial_success.rejected_data_points if signal=='metrics' else response.partial_success.rejected_spans
                rejected += n; sent += batch-n
                latency.append((time.monotonic()-t)*1000)
            except grpc.RpcError: errors += 1
            seq += 4
        channel.close()
        return sent, rejected, errors, latency
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(worker, range(4)))
    time.sleep(max(0, start+seconds-time.monotonic()))
    elapsed = time.monotonic()-start
    latency = sorted(v for output in outputs for v in output[3])
    return {'scheduled': int(rate*seconds)//batch*batch, 'accepted': sum(x[0] for x in outputs), 'rejected': sum(x[1] for x in outputs), 'rpc_errors': sum(x[2] for x in outputs), 'send_seconds': elapsed, 'accepted_per_second': sum(x[0] for x in outputs)/max(seconds,elapsed), 'ack_p95_ms': latency[min(len(latency)-1,int(len(latency)*.95))] if latency else None}


class Monitor:
    def __init__(self, process):
        self.process = psutil.Process(process.pid)
        self.samples = []; self.done = threading.Event()
        self.thread = threading.Thread(target=self.run)
    def run(self):
        while not self.done.is_set():
            try:
                processes = [self.process] + self.process.children(recursive=True)
                cpu = sum(p.cpu_times().user+p.cpu_times().system for p in processes)
                rss = sum(p.memory_info().rss for p in processes)
                self.samples.append((time.monotonic(), cpu, rss))
            except psutil.NoSuchProcess: break
            self.done.wait(.2)
    def __enter__(self): self.thread.start(); return self
    def __exit__(self, *args): self.done.set(); self.thread.join()
    def result(self):
        if len(self.samples)<2: return {'cpu_cores': None, 'rss_mb': None}
        first,last=self.samples[0],self.samples[-1]
        return {'cpu_cores': (last[1]-first[1])/(last[0]-first[0]), 'rss_mb': sum(x[2] for x in self.samples)/len(self.samples)/1024**2, 'peak_rss_mb': max(x[2] for x in self.samples)/1024**2}


def command(vendor, path, binary=None):
    commands = {'red': ['/opt/red/red','--config'], 'edgedelta': ['/opt/edgedelta/agent/edgedelta','-i','-c'], 'otelcol': ['/usr/bin/otelcol-contrib','--config'], 'bindplane': ['/opt/observiq-otel-collector/observiq-otel-collector','--config'], 'vector': ['/usr/local/bin/vector','--config'], 'fluentbit': ['/opt/fluent-bit/bin/fluent-bit','-c'], 'fluentd': ['/opt/fluent/bin/fluentd','--no-supervisor','-c']}
    result = commands[vendor]+[str(path.resolve())]
    if binary: result[0]=binary
    if vendor=='bindplane': result += ['--logging', str(Path(result[0]).parent/'logging.yaml')]
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--vendor', required=True)
    ap.add_argument('--output', default='otlp-results')
    ap.add_argument('--binary')
    ap.add_argument('--seconds', type=int, default=30)
    ap.add_argument('--rates', default='1000,10000')
    ap.add_argument('--scenarios', default='')
    args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    result={'vendor':args.vendor, 'commit':os.getenv('BENCHMARK_SHA','local'), 'platform':platform.platform(), 'cpu':platform.processor(), 'logical_cpus':os.cpu_count(), 'batch':512, 'concurrency':4, 'compression':'none', 'seconds':args.seconds, 'rows':[], 'calibration':[]}
    receiver_log=(out/'receiver.log').open('w')
    receiver=subprocess.Popen([sys.executable,'-m','otlpbench.receiver'],stdout=receiver_log,stderr=subprocess.STDOUT,start_new_session=True)
    def save(): (out/'results.json').write_text(json.dumps(result,indent=2))
    try:
        ready(receiver,14317)
        if args.vendor!='cribl':
            binary=command(args.vendor,out/'unused',args.binary)[0]
            version=subprocess.run([binary,'--version'],capture_output=True,text=True,timeout=10)
            result['version']=(version.stdout+version.stderr).strip()[:2000]
            import hashlib
            h = hashlib.sha256()
            with open(binary,'rb') as f:
                for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
            result['binary_sha256'] = h.hexdigest()
        for signal in SCENARIOS:
            for rate in map(int,args.rates.split(',')):
                sink('reset')
                c=load(signal,14317,rate,min(10,args.seconds))
                c.update(signal=signal,rate=rate,delivered=sink()['counts'][signal])
                c['passed']=c['accepted_per_second']>=rate*.95 and c['delivered']==c['accepted'] and not c['rpc_errors']
                result['calibration'].append(c)
        for signal,scenarios in SCENARIOS.items():
            for scenario in scenarios:
                if args.scenarios and scenario not in args.scenarios.split(','): continue
                row={'signal':signal,'scenario':scenario}; result['rows'].append(row)
                cfg,reason=config(args.vendor,signal,scenario)
                if cfg is None:
                    row.update(status='not_configured',detail=reason); save(); continue
                folder=out/f'{signal}-{scenario}'; folder.mkdir(exist_ok=True)
                path=folder/'agent.yaml'; path.write_text(cfg)
                env=dict(os.environ,ED_API_KEY='benchmark-local',ED_SKIP_CONF_DOWNLOAD='1',ED_BACKEND_DISABLED='1',ED_DISABLE_CONF_RELOAD='1',ED_COORDINATOR_CLIENT_DISABLED='1')
                log=(folder/'agent.log').open('w')
                p=subprocess.Popen(command(args.vendor,path,args.binary),env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    ready(p,4317); time.sleep(1); sink('reset-capture')
                    req=fixture(signal,512)
                    sent=list(records(signal,req))
                    # Splitting a logical batch catches transformations that only aggregate within one request.
                    pieces=[]
                    for parity in (0,1):
                        part=type(req)(); part.CopyFrom(req)
                        items=part.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points if signal=='metrics' else part.resource_spans[0].scope_spans[0].spans
                        keep=[x for i,x in enumerate(items) if i%2==parity]; del items[:]; items.extend(keep); pieces.append(part)
                    channel,export=client(signal,4317)
                    for part in pieces:
                        response=export(part,timeout=10)
                        if response.partial_success.ByteSize(): raise RuntimeError(f'partial OTLP rejection: {response.partial_success}')
                    channel.close()
                    drain=25 if scenario in ('aggregate','rollup','combined') else 4
                    time.sleep(drain)
                    received=sink()['records']
                    ok,detail=validate(signal,scenario,sent,received)
                    (folder/'correctness.json').write_text(json.dumps({'sent':sent,'received':received,'passed':ok,'detail':detail},indent=2))
                    row.update(status='correct' if ok else 'semantic_mismatch',detail=detail)
                    if not ok: continue
                    # Reset state by restarting the native process before measuring a fresh workload.
                    stop(p)
                    row['measurements']=[]
                    for rate in map(int,args.rates.split(',')):
                        cal=next(c for c in result['calibration'] if c['signal']==signal and c['rate']==rate)
                        if not cal['passed']:
                            row['measurements'].append({'rate':rate,'status':'generator_limited'}); continue
                        p=subprocess.Popen(command(args.vendor,path,args.binary),env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                        ready(p,4317)
                        # Drain warm-up before resetting the destination counts.
                        load(signal,4317,rate,5,sequence_offset=10000000)
                        time.sleep(drain)
                        sink('reset')
                        with Monitor(p) as monitor:
                            measurement=load(signal,4317,rate,args.seconds)
                        time.sleep(drain)
                        measurement.update(monitor.result())
                        delivered=sink()['counts']
                        measurement.update(rate=rate, delivered=delivered, status='measured', drain_seconds=drain)
                        if scenario != 'metrics':
                            fraction = .5 if scenario=='sample' else len(expected(signal,scenario,sent))/len(sent)
                            expected_count = measurement['accepted']*fraction
                            got = delivered[signal]
                            measurement['expected_output'] = expected_count
                            measurement['delivery_verified'] = abs(got-expected_count)<=expected_count*.1 if scenario=='sample' else got==expected_count
                            if not measurement['delivery_verified']: measurement['status']='delivery_shortfall'
                        if measurement['accepted_per_second'] < rate*.95: measurement['status']='input_shortfall'
                        row['measurements'].append(measurement)
                        stop(p)
                except Exception as exc:
                    row.update(status='error',detail=f'{type(exc).__name__}: {exc}')
                finally:
                    stop(p); log.close(); save()
                print(json.dumps(row),flush=True)
    finally:
        stop(receiver); receiver_log.close(); save()


if __name__=='__main__': main()
