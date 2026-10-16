"""Integration checks for the Rust traffic harness (build --release first)."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request

from .model import fixture


class TrafficTest(unittest.TestCase):
    def test_delivery_and_accounting(self):
        binary = Path(os.environ.get('OTLP_TRAFFIC_BINARY', Path(__file__).parent/'traffic-rs/target/release/otlp-traffic'))
        if not binary.exists(): self.skipTest('build the Rust traffic harness first')
        def port():
            with socket.socket() as s:
                s.bind(('127.0.0.1',0)); return s.getsockname()[1]
        grpc_port, http_port = port(), port()
        with tempfile.TemporaryDirectory() as tmp:
            f = fixture('metrics', 16)
            f.resource_metrics[0].resource.attributes[1].value.string_value='00000000000000000000'
            path = Path(tmp)/'fixture.pb'; path.write_bytes(f.SerializeToString())
            sink = subprocess.Popen([str(binary),'sink','--grpc-addr',f'127.0.0.1:{grpc_port}','--http-addr',f'127.0.0.1:{http_port}'])
            base = f'http://127.0.0.1:{http_port}'
            def call(path, data=None):
                with urllib.request.urlopen(urllib.request.Request(base+path,data=data),timeout=5) as response:
                    return response.read()
            try:
                for _ in range(100):
                    try: call('/stats'); break
                    except OSError: time.sleep(.02)
                else: self.fail('sink failed to start')
                r = json.loads(subprocess.check_output([str(binary),'load','--fixture',str(path),'--endpoint',f'http://127.0.0.1:{grpc_port}','--rps','1000','--seconds','1','--connections','2','--concurrency','16'],text=True))
                actual=json.loads(call('/stats'))
                self.assertEqual(r['scheduled_requests'],r['started']+r['missed_requests'])
                self.assertEqual(r['started'],r['completed']+r['rpc_errors'])
                self.assertEqual(r['rpc_errors'],0)
                self.assertGreater(r['completed'],0)
                self.assertEqual(actual['points'],r['accepted_points'])
                self.assertEqual(actual['points'],r['completed']*16)
                self.assertEqual(actual['value_sum'],actual['points'])
                self.assertEqual(sum(r['latency_buckets']),r['started'])
                call('/reset',b'')
                req=urllib.request.Request(base+'/v1/metrics',data=f.SerializeToString(),headers={'Content-Type':'application/x-protobuf'})
                with urllib.request.urlopen(req,timeout=5) as response: self.assertEqual(response.status,200)
                self.assertEqual(json.loads(call('/stats'))['points'],16)
                path.write_bytes(b'bad protobuf')
                failed=subprocess.run([str(binary),'load','--fixture',str(path)],capture_output=True)
                self.assertNotEqual(failed.returncode,0)
            finally:
                sink.terminate();sink.wait(timeout=5)


if __name__=='__main__': unittest.main()
