import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import fetch_red
import parallel

class ReleaseTest(unittest.TestCase):
    def test_verified_release_and_checksum_rejection(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('red', b'fixture binary')
        data = buf.getvalue()
        def download(url, output=None):
            if output:
                Path(output).write_bytes(data)
            elif url.endswith('stable-version'):
                return b'3.12.0\n'
            else:
                return hashlib.sha256(data).hexdigest().encode()
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch_red, 'download', side_effect=download):
            result = fetch_red.fetch(tmp)
            self.assertEqual(result['version'], '3.12.0')
            self.assertEqual(result['binary_sha256'], hashlib.sha256(b'fixture binary').hexdigest())
            self.assertEqual((Path(tmp) / 'red').stat().st_mode & 0o777, 0o755)
        with tempfile.TemporaryDirectory() as tmp:
            def bad(url, output=None):
                if output:
                    Path(output).write_bytes(data)
                else:
                    return b'0' * 64
            with patch.object(fetch_red, 'download', side_effect=bad), self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                fetch_red.fetch(tmp, '3.12.0')
            self.assertFalse((Path(tmp) / 'red').exists())
        with self.assertRaisesRegex(ValueError, 'stable'):
            fetch_red.fetch('/unused', '../bad')

    def test_stable_pointer_falls_back_to_latest_github_release(self):
        html = lambda url, output=None: b'<!doctype html><title>Releases</title>4.3.1'
        with patch.object(fetch_red, 'download', side_effect=html):
            with patch.dict('os.environ', {'GH_TOKEN': 'token'}), \
                    patch.object(fetch_red.subprocess, 'check_output', return_value=b'v3.15.0\n') as gh:
                self.assertEqual(fetch_red.stable_version(), '3.15.0')
                self.assertIn('repos/edgedelta/red/releases/latest', gh.call_args.args[0])
            with patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(ValueError, 'RED_VERSION'):
                fetch_red.stable_version()

class ParallelTest(unittest.TestCase):
    def test_plan(self):
        plan = parallel.plan(','.join(parallel.VENDORS), ','.join(parallel.CASES))
        self.assertEqual(len(plan['include']), 8)
        fb = next(j for j in plan['include'] if j['vendor'] == 'fluentbit')
        self.assertNotIn('mask', fb['cases'])
        with self.assertRaises(ValueError):
            parallel.plan('fluentbit', 'mask')

    def shards(self, root):
        for vendor in ['red', 'vector']:
            path = root / vendor
            path.mkdir()
            (path / 'versions.csv').write_text(f'agent,version\n{vendor},1.0\n')
            (path / 'provenance.json').write_text(json.dumps({'instance_id': vendor, 'benchmark_commit': 'a'*40, 'loadgen_version': 'patched', 'loadgen': {'retry_ambiguous': True}}))
            (path / f'{vendor}_pass-through.log').write_text(''.join(f'Starting loadgen with {w} workers\n[STATS] current: 100 logs/sec | avg: 100 logs/sec | total: 6000 | errors: 0 | connection_errors: 1 | retry_attempts: 1 | recovered_requests: 1 | ambiguous_deliveries: 1\n[MONITOR - TARGET] pid: 1 | cpu: 10.0% | memory: 10.0MB\nFinished loadgen with {w} workers\n' for w in [80,100,120]))

    def test_merge_and_reject_bad_shards(self):
        matrix = {'include': [{'vendor': v, 'cases': 'pass-through'} for v in ['red', 'vector']]}
        for fault in [None, 'shared-instance', 'different-policy', 'missing-shard', 'missing-counters']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'shards'; root.mkdir(); self.shards(root)
                path = root / 'vector' / 'provenance.json'
                provenance = json.loads(path.read_text())
                if fault == 'shared-instance': provenance['instance_id'] = 'red'
                if fault == 'different-policy': provenance['loadgen']['max_retries'] = 1
                path.write_text(json.dumps(provenance))
                if fault == 'missing-shard': (root/'vector'/'versions.csv').unlink()
                if fault == 'missing-counters':
                    log = root/'vector'/'vector_pass-through.log'
                    log.write_text(log.read_text().replace(' | retry_attempts: 1', ''))
                output = Path(tmp) / 'out'
                if fault:
                    with self.assertRaises(ValueError): parallel.merge(root, output, matrix)
                else:
                    parallel.merge(root, output, matrix)
                    result = json.loads((output/'data.json').read_text())
                    self.assertEqual(result['scenarios']['red/pass-through']['status'], 'ok')
                    self.assertEqual(len(result['provenance']['shards']), 2)
