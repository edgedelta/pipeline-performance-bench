import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

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
        self.assertEqual(summary.parse_log(text)['tier_mean'], 100)
        for bad in [text.replace('errors: 0', 'errors: 1'), text.replace('Finished loadgen with 120', 'missing'), text + 'ERROR: service restarted', '']:
            self.assertEqual(summary.parse_log(bad)['status'], 'invalid')

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

    def test_report_distinguishes_missing_from_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = summary.summarize(Path(tmp))
            self.assertEqual(run['scenarios']['fluentbit/mask']['status'], 'unsupported')
            self.assertEqual(run['scenarios']['vector/mask']['status'], 'not-run')
            self.assertIsNone(run['vendors']['vector']['avg'][0])

if __name__ == '__main__':
    unittest.main()
