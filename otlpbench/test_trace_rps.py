"""Trace transport, identity and operation checks for the request-rate harness."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from .model import fixture, attrs
from .rps import matched_output_config, trace_verified


def trace_fixture(batch=512):
    req = fixture('traces', batch)
    attrs(req.resource_spans[0].resource.attributes, {'bench.batch': '00000000000000000000'})
    for i, span in enumerate(req.resource_spans[0].scope_spans[0].spans):
        span.trace_id = b'BENCHID!' + (i//2+1).to_bytes(8, 'big')
    return req


class TraceTest(unittest.TestCase):
    def test_trace_chart_keeps_sampling_checks_explicit(self):
        from .ladder_chart import collect, render, TRACE_SCENARIOS
        with tempfile.TemporaryDirectory() as tmp:
            report=collect(Path(tmp),'e12daf8','hash',True,'traces')
            self.assertEqual(report['scenarios'],TRACE_SCENARIOS)
            self.assertEqual(len(report['rows']),60)
            html=render(report)
            self.assertIn('Spans/sec per core',html)
            self.assertIn('sampling_verified',html)
            self.assertIn('does not independently prove',html)
            self.assertNotIn('Aggregate uses native behavior',html)
            path=Path(tmp)/'pass-through';path.mkdir()
            (path/'results.json').write_text(json.dumps(dict(signal='metrics',rows=[],calibration=[])))
            with self.assertRaises(ValueError): collect(Path(tmp),'e12daf8','hash',True,'traces')

    def test_native_configs(self):
        for vendor in ('red', 'otelcol', 'bindplane'):
            for scenario in ('pass-through','filter','mask','sample','tail'):
                cfg = matched_output_config(vendor,'10.0.0.1',scenario=scenario,signal='traces')
                if vendor != 'red':
                    self.assertIn('traces',cfg['service']['pipelines'])
                    self.assertNotIn('batch',cfg.get('processors',{}))
                if scenario == 'tail':
                    size = cfg['nodes'][1]['processors'][0]['cache']['batch']['size'] if vendor == 'red' else cfg['processors']['tail_sampling/bench']['num_traces']
                    self.assertEqual(size,4_000_000)

    def test_operation_gates(self):
        checks=dict(invalid=0,roots=256,children=256,root_ids=123,child_ids=123,private=512,masked=0,error_trace_spans=128)
        s=dict(points=512,health_points=128,trace_checks=checks)
        self.assertTrue(trace_verified('pass-through',s,512))
        self.assertFalse(trace_verified('mask',s,512))
        self.assertFalse(trace_verified('tail',s,512))
        self.assertFalse(trace_verified('filter',s,512))
        self.assertTrue(trace_verified('sample',s,1024))
        self.assertFalse(trace_verified('sample',s,2048))
        for field,value in [('invalid',1),('child_ids',124),('children',255),('private',511)]:
            self.assertFalse(trace_verified('pass-through',dict(s,trace_checks=dict(checks,**{field:value})),512))

    def test_grpc_and_http_trace_delivery(self):
        binary=Path(__file__).parent/'traffic-rs/target/release/otlp-traffic'
        def port():
            with socket.socket() as s:
                s.bind(('127.0.0.1',0)); return s.getsockname()[1]
        grpc_port,http_port=port(),port()
        proc=subprocess.Popen([str(binary),'sink','--grpc-addr',f'127.0.0.1:{grpc_port}','--http-addr',f'127.0.0.1:{http_port}'])
        def call(path,data=None):
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{http_port}'+path,data=data),timeout=5) as r: return r.read()
        try:
            for _ in range(100):
                try: call('/stats'); break
                except OSError: time.sleep(.02)
            else: self.fail('trace sink did not start')
            with tempfile.TemporaryDirectory() as tmp:
                f=trace_fixture(); path=Path(tmp)/'traces.pb';path.write_bytes(f.SerializeToString())
                result=json.loads(subprocess.check_output([str(binary),'load','--signal','traces','--fixture',str(path),'--endpoint',f'http://127.0.0.1:{grpc_port}','--rps','100','--seconds','1','--connections','2','--concurrency','16'],text=True))
                s=json.loads(call('/stats'))
                self.assertEqual(result['rpc_errors'],0)
                self.assertGreater(result['completed'],0)
                self.assertEqual(s['points'],result['accepted_points'])
                self.assertTrue(trace_verified('pass-through',s,result['accepted_points']))
                call('/reset',b'')
                call('/v1/traces',f.SerializeToString())
                s=json.loads(call('/stats'))
                self.assertTrue(trace_verified('pass-through',s,512))
                for span in f.resource_spans[0].scope_spans[0].spans:
                    for a in span.attributes:
                        if a.key=='secret': a.value.string_value='REDACTED'
                call('/reset',b'');call('/v1/traces',f.SerializeToString())
                self.assertTrue(trace_verified('mask',json.loads(call('/stats')),512))
                f.resource_spans[0].scope_spans[0].spans[0].name='corrupt'
                call('/reset',b'');call('/v1/traces',f.SerializeToString())
                self.assertFalse(trace_verified('mask',json.loads(call('/stats')),512))
        finally:
            proc.terminate();proc.wait(timeout=5)
