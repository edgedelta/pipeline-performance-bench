#!/usr/bin/env python3
"""Exercise both real binaries against identical fault-injecting HTTP fixtures."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from fixed import phase
ROOT=Path(__file__).resolve().parents[1]

class Receiver(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    mode='ok'
    count=0
    received=[]
    connections=set()
    def setup(self):
        super().setup()
        type(self).connections.add(self.client_address)
        self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    def log_message(self,*args): pass
    def do_POST(self):
        body=self.rfile.read(int(self.headers['Content-Length']))
        type(self).received.append(body)
        type(self).count+=1
        mode=type(self).mode
        if mode=='recover' and type(self).count%2==1 or mode in ('disconnect','no_retry'):
            self.close_connection=True
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        if mode in ('slow','timeout'): time.sleep(.12)
        status=int(mode) if mode.isdigit() else 200
        self.send_response(status)
        if mode=='chunked': self.send_header('Transfer-Encoding','chunked')
        else: self.send_header('Content-Length','10' if mode=='truncated' else '0')
        if mode in ('close','recover','truncated'): self.send_header('Connection','close')
        self.end_headers()
        if mode=='chunked': self.wfile.write(b'3\r\nabc\r\n0\r\n\r\n')
        if mode=='truncated': self.wfile.write(b'a')
        if mode in ('close','recover','truncated'): self.close_connection=True

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def handle_error(self,*args): pass

def check(binary, mode, directory, workers=1, tasks=False):
    Receiver.mode=mode; Receiver.count=0; Receiver.received=[]; Receiver.connections=set()
    server=Server(('127.0.0.1',0),Receiver)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    if mode=='refused': server.shutdown(); server.server_close()
    output=Path(directory)/'result.json'
    command=[binary,'--endpoint',f'http://127.0.0.1:{server.server_port}/ingest','--number','1','--workers',str(workers),'--fixed-rate','50','--timeout','1s','--max-retries','2','--retry-ambiguous','--fixed-warmup','0s','--total-time','2s','--fixed-payload-file',str(ROOT/'payloads/fixed-nginx.ndjson'),'--fixed-output',str(output)]
    if tasks: command += ['--dispatch-mode','tasks','--max-inflight',str(workers),'--pending-capacity',str(workers)]
    if mode=='no_retry': command.remove('--retry-ambiguous')
    if mode=='timeout': command[command.index('--timeout')+1]='30ms'
    try:
        proc=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if mode=='signal': time.sleep(.25); proc.send_signal(signal.SIGTERM)
        _,stderr=proc.communicate(timeout=10)
        assert proc.returncode==0,stderr.decode()
        raw=json.loads(output.read_text()); p=raw['measurement']
        assert raw['payload_sha256']==hashlib.sha256((ROOT/'payloads/fixed-nginx.ndjson').read_bytes()).hexdigest()
        corpus=set((ROOT/'payloads/fixed-nginx.ndjson').read_bytes().strip().splitlines())
        if mode!='refused': assert Receiver.received and all(b.endswith(b'\n') and b.strip() in corpus for b in Receiver.received)
        if mode=='signal':
            assert p['canceled'] is True
            assert p['dispatched_logs']==p['acknowledged_logs']+p['acknowledged_after_window']+p['errors']
            return
        phase(raw,2,require_agent=False)
        if tasks:
            assert raw['workers'] is None and raw['dispatch_mode']=='tasks'
            assert 0 < p['peak_admitted_tasks'] <= 2*workers
            assert p['admission_dropped_logs']==p['worker_queue_dropped_logs']
        assert p['scheduled_logs']==100
        assert p['offered_logs']<=100
        if mode in ('ok','chunked','close'):
            assert 90<=p['acknowledged_logs']<=100,p
            assert p['errors']==p['ambiguous_deliveries']==0,p
        elif mode=='recover':
            assert p['recovered_requests']>0 and p['ambiguous_deliveries']>0,p
            assert p['errors']==0,p
        elif mode=='no_retry':
            assert p['errors']==p['dispatched_logs'] and p['retry_attempts']==0,p
            assert p['ambiguous_deliveries']==p['dispatched_logs'],p
        elif mode=='timeout':
            assert p['errors']==p['dispatched_logs'] and p['retry_attempts']==p['connection_errors']==0,p
        elif mode=='refused':
            assert p['errors']==p['dispatched_logs'] and p['retry_attempts']==2*p['dispatched_logs'],p
            assert p['offered_logs']==p['ambiguous_deliveries']==0,p
        elif mode=='disconnect':
            assert p['acknowledged_logs']==0 and p['errors']>0,p
            assert p['retry_attempts']==2*p['dispatched_logs'],p
            assert p['ambiguous_deliveries']==p['dispatched_logs'],p
        elif mode in ('429','503','400'):
            assert p['errors']==p['dispatched_logs'] and p['retry_attempts']==0,p
            assert p['backpressure']==(p['errors'] if mode in ('429','503') else 0),p
            assert len(Receiver.connections)==1, 'HTTP rejection should preserve keep-alive'
        elif mode=='302':
            assert p['http_status_counts']=={'302':p['dispatched_logs']} and p['retry_attempts']==0,p
        elif mode=='truncated':
            assert p['errors']==p['dispatched_logs'] and p['retry_attempts']==p['acknowledged_logs']==0,p
        elif mode=='slow':
            assert p['acknowledged_after_window']>0 and p['errors']==0,p
    finally:
        server.shutdown(); server.server_close()

def main():
    p=argparse.ArgumentParser(); p.add_argument('binaries',nargs='+'); p.add_argument('--task-mode',action='store_true'); p.add_argument('--modes',default='ok,chunked,close,recover,disconnect,429,503,400,302,truncated,slow,signal,no_retry,timeout,refused'); a=p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        for binary in a.binaries:
            for mode in a.modes.split(','):
                check(str(Path(binary).resolve()),mode,tmp,tasks=a.task_mode)
                print(Path(binary).name,mode,'PASS',flush=True)
            check(str(Path(binary).resolve()),'ok',tmp,workers=16,tasks=a.task_mode)
            print(Path(binary).name,'global rate with 16 workers PASS',flush=True)
if __name__=='__main__': main()
