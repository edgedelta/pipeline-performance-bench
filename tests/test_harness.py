import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_results

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('summarize', ROOT / 'tools/summarize.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)

class HarnessTest(unittest.TestCase):
    def test_shell_syntax(self):
        for path in ROOT.rglob('*.sh'):
            subprocess.run(['bash', '-n', str(path)], check=True)

    def test_matrix_without_credentials_or_cwd(self):
        result = subprocess.run([str(ROOT / 'run.sh'), '--dry-run'], cwd='/tmp', text=True, capture_output=True, check=True, env={'PATH': '/usr/bin:/bin'})
        self.assertIn('vector: pass-through filter mask lookup', result.stdout)
        self.assertIn('fluentbit: pass-through filter lookup', result.stdout)
        self.assertIn('red: pass-through filter mask lookup', result.stdout)

    def test_invalid_selection(self):
        for args in [['--vendors', 'bogus'], ['--cases', ''], ['--vendors']]:
            result = subprocess.run([str(ROOT / 'run.sh'), '--dry-run', *args], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_unsupported_case(self):
        result = subprocess.run([str(ROOT / 'run.sh'), '--dry-run', '--vendors', 'fluentbit', '--cases', 'mask'], text=True, capture_output=True, check=True)
        self.assertTrue(result.stdout.endswith('fluentbit: \n'))

    def test_report_rejects_failed_or_partial_runs(self):
        text = ''.join(f'Starting loadgen with {w} workers for vector\n[STATS] avg: {w} logs/sec | errors: 0\n[MONITOR - TARGET] pid: 1 | cpu: 100.0% | memory: 10.0MB\nFinished loadgen with {w} workers for vector\n' for w in [80, 100, 120])
        self.assertEqual(summary.parse_log(text)['avg'], 120)
        self.assertEqual(summary.parse_log(text, require_retries=True)['status'], 'invalid')
        self.assertEqual(summary.parse_log(text)['tier_mean'], 100)
        for bad in [text.replace('Finished loadgen with 120', 'missing'), text + 'ERROR: service restarted', '']:
            self.assertEqual(summary.parse_log(bad)['status'], 'invalid')

    def test_completed_http_errors_remain_visible(self):
        text = ''.join(f'Starting loadgen with {w} workers for red\n[STATS] avg: 100 logs/sec | errors: 2\nFinished loadgen with {w} workers for red\n' for w in [80, 100, 120])
        data = summary.parse_log(text)
        self.assertEqual(data['status'], 'errors')
        self.assertEqual(data['avg'], 100)
        self.assertEqual(sum(tier['errors'] for tier in data['workers']), 6)

    def test_recovered_errors_are_ranked_and_counters_preserved(self):
        text = ''.join(f'Starting loadgen with {w} workers\n[STATS] current: 100 logs/sec | avg: 100 logs/sec | total: 6000 | errors: 0 | backpressure: 0 | connection_errors: 3 | retry_attempts: 3 | recovered_requests: 2 | ambiguous_deliveries: 2\nFinished loadgen with {w} workers\n' for w in [80, 100, 120])
        parsed = summary.parse_log(text)
        self.assertEqual(parsed['status'], 'ok')
        self.assertEqual(sum(t['connection_errors'] for t in parsed['workers']), 9)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'red_pass-through.log').write_text(text)
            data = summary.summarize(path)
            self.assertEqual(data['vendors']['red']['avg'][0], 100)
            self.assertIn('| Edge Delta (Rust) | 9 | 9 | 6 | 6 |', (path / 'report.md').read_text())
        self.assertEqual(summary.parse_log(text.replace(' | retry_attempts: 3', ''))['status'], 'invalid')
        self.assertEqual(summary.parse_log(text.replace('recovered_requests: 2', 'recovered_requests: 4'))['status'], 'invalid')
        self.assertEqual(summary.parse_log(text.replace('errors: 0 | backpressure', 'errors: 1 | backpressure'))['status'], 'errors')

    def test_best_tier_uses_matching_resource_samples(self):
        text = ''.join(f'Starting loadgen with {w} workers for vector\n[STATS] current: {rate + 10} logs/sec | avg: {rate} logs/sec | total: {rate * 60} | errors: 0 | backpressure: 0\n[MONITOR - TARGET] pid: 1 | cpu: {w}.0% | memory: {w}.0MB\nFinished loadgen with {w} workers for vector\n' for w, rate in [(80, 100), (100, 300), (120, 200)])
        data = summary.parse_log(text)
        self.assertEqual((data['best_workers'], data['avg'], data['peak'], data['cpu'], data['mem']), (100, 300, 310, 100, 100))

    def test_multiple_processes_are_summed(self):
        text = ''.join(f'Starting loadgen with {w} workers for cribl\n[STATS] avg: 100 logs/sec | errors: 0\n[MONITOR - TARGET] pid: 1 | cpu: 10.0% | memory: 20.0MB\n[MONITOR - TARGET] pid: 2 | cpu: 100.0% | memory: 200.0MB\nFinished loadgen with {w} workers for cribl\n' for w in [80, 100, 120])
        data = summary.parse_log(text)
        self.assertEqual((data['cpu'], data['mem']), (110, 220))

    def test_missing_reliability_is_not_assumed_zero(self):
        text = ''.join(f'Starting loadgen with {w} workers for vector\n[STATS] avg: 10 logs/sec\nFinished loadgen with {w} workers for vector\n' for w in [80, 100, 120])
        self.assertEqual(summary.parse_log(text)['status'], 'invalid')

    def test_release_rejects_empty_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "missing recorded version"):
                check_results.validate(Path(tmp))

    def test_release_retains_errors_without_charting_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'versions.csv').write_text('agent,version\n' + ''.join(f'{v},1.0\n' for v in summary.VENDORS))
            # "unknown" is a legitimate part of Rust's target triple.
            versions = directory / 'versions.csv'
            versions.write_text(versions.read_text().replace('vector,1.0', 'vector,vector 0.55.0 (x86_64-unknown-linux-gnu)'))
            (directory / 'provenance.json').write_text(json.dumps({'benchmark_commit': 'a' * 40, 'rust_commit': 'b' * 40}))
            for vendor in summary.VENDORS:
                for case in summary.CASES:
                    if (vendor, case) in summary.UNSUPPORTED:
                        continue
                    errors = 2 if vendor == 'red' else 0
                    text = ''.join(f'Starting loadgen with {w} workers\n[STATS] current: 100 logs/sec | avg: 100 logs/sec | total: 6000 | errors: {errors} | backpressure: 0\n[MONITOR - TARGET] pid: 1 | cpu: 10.0% | memory: 20.0MB\nFinished loadgen with {w} workers\n' for w in [80, 100, 120])
                    (directory / f'{vendor}_{case}.log').write_text(text)
            data = check_results.validate(directory)
            self.assertEqual(data['scenarios']['red/pass-through']['status'], 'errors')
            self.assertEqual(data['vendors']['red']['avg'], [None] * 4)
            report = (directory / 'report.md').read_text()
            self.assertIn('| Edge Delta (Rust) | errors | 80 | 100.00 logs/sec |', report)
            self.assertIn('| Edge Delta (Rust) | 6 | 0 | errors |', report)
            self.assertEqual(len((directory / 'SHA256SUMS').read_text().splitlines()), 30)

    def test_report_distinguishes_missing_from_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = summary.summarize(Path(tmp))
            self.assertEqual(run['scenarios']['fluentbit/mask']['status'], 'unsupported')
            self.assertEqual(run['scenarios']['vector/mask']['status'], 'not-run')
            self.assertIsNone(run['vendors']['vector']['avg'][0])

if __name__ == '__main__':
    unittest.main()
