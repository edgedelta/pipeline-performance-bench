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
from .rps import output_batch_matches, matched_output_config


class TrafficTest(unittest.TestCase):
    def test_output_batch_gate_rejects_mixed_sizes_with_same_average(self):
        self.assertTrue(output_batch_matches({'requests':2,'points':1024,'request_points':{'512':2}},512))
        self.assertFalse(output_batch_matches({'requests':2,'points':1024,'request_points':{'1':1,'1023':1}},512))
        self.assertFalse(output_batch_matches({'requests':0,'points':0,'request_points':{}},512))
        self.assertFalse(output_batch_matches({'requests':2,'points':1024},512))

    def test_config_preserves_input_batches(self):
        for vendor in ['otelcol','bindplane']:
            c=matched_output_config(vendor,'127.0.0.1')
            self.assertNotIn('processors',c)
            self.assertEqual(c['service']['pipelines']['metrics']['processors'],[])
            self.assertFalse(c['exporters']['otlphttp']['sending_queue']['enabled'])
            self.assertEqual(c['exporters']['otlphttp']['max_idle_conns_per_host'],1024)
            self.assertEqual(c['exporters']['otlphttp']['max_conns_per_host'],1024)
        self.assertEqual(matched_output_config('otelcol','127.0.0.1',64)['exporters']['otlphttp']['max_conns_per_host'],64)
        self.assertEqual(matched_output_config('red','127.0.0.1')['settings'],{'tag':'otlp-benchmark'})

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
                r = json.loads(subprocess.check_output([str(binary),'load','--fixture',str(path),'--endpoint',f'http://127.0.0.1:{grpc_port}','--rps','1000','--seconds','1','--connections','2','--concurrency','16','--series-groups','4'],text=True))
                actual=json.loads(call('/stats'))
                self.assertEqual(r['scheduled_requests'],r['started']+r['missed_requests'])
                self.assertEqual(r['started'],r['completed']+r['rpc_errors'])
                self.assertEqual(r['rpc_errors'],0)
                self.assertGreater(r['completed'],0)
                self.assertEqual(actual['points'],r['accepted_points'])
                self.assertEqual(actual['points'],r['completed']*16)
                self.assertTrue(output_batch_matches(actual,16))
                self.assertEqual(actual['request_points'],{'16':r['completed']})
                self.assertEqual(actual['value_sum'],actual['points'])
                self.assertEqual(actual['host_points'],actual['points'])
                self.assertEqual(actual['health_points'],actual['points']//4)
                self.assertEqual(actual['enriched_points'],0)
                self.assertEqual(sum(r['latency_buckets']),r['started'])
                call('/reset',b'')
                req=urllib.request.Request(base+'/v1/metrics',data=f.SerializeToString(),headers={'Content-Type':'application/x-protobuf'})
                with urllib.request.urlopen(req,timeout=5) as response: self.assertEqual(response.status,200)
                self.assertEqual(json.loads(call('/stats'))['points'],16)
                self.assertEqual(json.loads(call('/stats'))['request_points'],{'16':1})
                path.write_bytes(b'bad protobuf')
                failed=subprocess.run([str(binary),'load','--fixture',str(path)],capture_output=True)
                self.assertNotEqual(failed.returncode,0)
            finally:
                sink.terminate();sink.wait(timeout=5)


class ScenarioTest(unittest.TestCase):
    def test_operation_checks(self):
        from .rps import scenario_verified
        base=dict(points=512,value_sum=512,host_points=512,health_points=128,enriched_points=0)
        self.assertFalse(scenario_verified('enrich',base,512,512))
        self.assertTrue(scenario_verified('enrich',dict(base,enriched_points=512),512,512))
        self.assertTrue(scenario_verified('filter',dict(base,points=384,value_sum=384,health_points=0),512,512))
        self.assertFalse(scenario_verified('filter',base,512,512))
        self.assertFalse(scenario_verified('aggregate',dict(base,host_points=0),512,512))
        self.assertTrue(scenario_verified('aggregate',dict(base,points=2,host_points=0),512,512))
        self.assertTrue(scenario_verified('rollup',dict(base,points=64,host_points=64),512,512))
        self.assertFalse(scenario_verified('rollup',dict(base,points=64,host_points=0),512,512))

    def test_scenario_processors_retained(self):
        from .rps import matched_output_config
        for vendor in ['otelcol','bindplane']:
            for scenario in ['filter','enrich','aggregate','rollup','combined']:
                c=matched_output_config(vendor,'127.0.0.1',scenario=scenario)
                self.assertTrue(c['processors'])
                self.assertNotIn('batch',c['processors'])


if __name__=='__main__': unittest.main()
