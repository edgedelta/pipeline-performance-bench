import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import fetch_red
import publish_otlp


class DailyEvidenceTest(unittest.TestCase):
    def test_candidate_package_binds_release_to_source(self):
        binary = b'linux candidate fixture'
        commit = 'a' * 40
        manifest = dict(qualification='PASS', candidate_version='3.15.0-rc.34', version='3.15.0', commit=commit)
        for package_commit in [commit, 'b' * 40]:
            with self.subTest(package_commit=package_commit), tempfile.TemporaryDirectory() as tmp:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as archive:
                    archive.writestr('red', binary)
                    archive.writestr('manifest.json', json.dumps(dict(commit=package_commit, profile='release', target='x86_64-unknown-linux-gnu', worktree_dirty=False, sha256=hashlib.sha256(binary).hexdigest())))
                data = buf.getvalue()
                def download(url, output=None):
                    if output:
                        Path(output).write_bytes(data)
                    elif url.endswith('release-manifest.json'):
                        return json.dumps(manifest).encode()
                    else:
                        return hashlib.sha256(data).hexdigest().encode()
                releases = json.dumps([dict(draft=False, prerelease=True, tag_name='v3.15.0-rc.34')])
                with patch.object(fetch_red.subprocess, 'check_output', return_value=releases), patch.object(fetch_red, 'download', side_effect=download):
                    if package_commit == commit:
                        result = fetch_red.fetch_candidate(tmp)
                        self.assertEqual(result['source_commit'], commit)
                        self.assertEqual(result['channel'], 'candidate')
                    else:
                        with self.assertRaisesRegex(ValueError, 'source/build mismatch'):
                            fetch_red.fetch_candidate(tmp)
                        self.assertFalse((Path(tmp) / 'red').exists())

    def test_package_requires_complete_pair_same_binary_and_commit(self):
        base = dict(profile='full', benchmark_commit='a'*40, binary_sha256='b'*64, rows=[dict(status='measured') for _ in range(60)])
        for mutation in ['none', 'missing', 'partial', 'wrong_commit', 'wrong_binary', 'invalid', 'short']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'raw'
                for signal in ['metrics', 'traces']:
                    if mutation == 'missing' and signal == 'traces':
                        continue
                    directory = root / signal
                    directory.mkdir(parents=True)
                    data = copy.deepcopy(base)
                    if signal == 'traces':
                        if mutation == 'partial': data['rows'].pop()
                        if mutation == 'wrong_commit': data['benchmark_commit'] = 'c'*40
                        if mutation == 'wrong_binary': data['binary_sha256'] = 'c'*64
                        if mutation == 'invalid': data['rows'][0]['status'] = 'operation_mismatch'
                        if mutation == 'short': data['profile'] = 'short'
                    (directory / f'{signal}.json').write_text(json.dumps(data))
                output = Path(tmp) / 'out'
                if mutation == 'none':
                    publish_otlp.package(root, output, base['benchmark_commit'])
                    self.assertTrue((output / 'otlp-evidence.tar.gz').exists())
                    self.assertEqual(len((output / 'SHA256SUMS').read_text().splitlines()), 3)
                else:
                    with self.assertRaises(ValueError):
                        publish_otlp.package(root, output, base['benchmark_commit'])


if __name__ == '__main__':
    unittest.main()

class VendorShardTest(unittest.TestCase):
    def shards(self, root, profile='full'):
        import otlp_daily
        paths = []
        for vendor in ['red', 'otelcol', 'bindplane']:
            rates = otlp_daily.RATES['metrics'] if profile == 'full' else [1000]
            scenarios = otlp_daily.SCENARIOS
            data = dict(schema='metrics-request-ladder-v1', signal='metrics', profile=profile,
                        benchmark_commit='a'*40, source_commit='b'*40, binary_sha256='c'*64,
                        rust_release={'version':'test'}, seconds=60 if profile=='full' else 10,
                        batch=512, trials=1, run_url='run', vendors=[vendor], rates=rates,
                        scenarios=scenarios, measured_at='2026-10-18', versions={vendor:'1.0.0'})
            data['rows'] = [dict(vendor=vendor, scenario=s, target_rps=r, batch=512, trial=0,
                                 status='measured', operation_verified=True, delivery_verified=True,
                                 binary_sha256='c'*64) for s in scenarios for r in rates]
            data['calibration'] = [dict(scenario=s, target_rps=r, passed=True) for s in scenarios for r in rates]
            path = root / (vendor+'.json'); path.write_text(json.dumps(data)); paths.append(path)
        return paths

    def test_merge_complete_and_reject_corrupt_shards(self):
        for mutation in ['none', 'missing', 'duplicate_vendor', 'missing_row', 'duplicate_row', 'wrong_vendor', 'wrong_binary', 'wrong_commit', 'failed_delivery', 'failed_calibration', 'duplicate_calibration']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = self.shards(Path(tmp))
                data = json.loads(paths[-1].read_text())
                if mutation == 'missing': paths.pop()
                if mutation == 'duplicate_vendor': data['vendors']=['red']
                if mutation == 'missing_row': data['rows'].pop()
                if mutation == 'duplicate_row': data['rows'][-1]=data['rows'][0]
                if mutation == 'wrong_vendor': data['rows'][0]['vendor']='red'
                if mutation == 'wrong_binary': data['binary_sha256']='d'*64
                if mutation == 'wrong_commit': data['benchmark_commit']='d'*40
                if mutation == 'failed_delivery': data['rows'][0]['delivery_verified']=False
                if mutation == 'failed_calibration': data['calibration'][0]['passed']=False
                if mutation == 'duplicate_calibration': data['calibration'][-1]=data['calibration'][0]
                if mutation != 'missing': paths[-1].write_text(json.dumps(data))
                if mutation == 'none':
                    result=publish_otlp.merge_signal(paths, 'metrics', 'a'*40)
                    self.assertEqual(len(result['rows']),60)
                    self.assertEqual(len(result['calibration']),60)
                    self.assertEqual(result['vendors'],['red','otelcol','bindplane'])
                else:
                    with self.assertRaises(ValueError): publish_otlp.merge_signal(paths,'metrics','a'*40)

    def test_short_shards(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=publish_otlp.merge_signal(self.shards(Path(tmp),'short'),'metrics','a'*40,'short')
            self.assertEqual(len(result['rows']),15)
