"""Generator selection, artifact integrity, and historical-result compatibility."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'benchmark_scripts'))
import generator_bundle as bundle
import fixed
import preview_release as fixture
import run_fixed
import yaml


class GeneratorBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        # Synthetic ELF headers only: never executed or used as measurements.
        for name in ('loadgen', 'loadgen-rust'):
            (self.directory / name).write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00' + name.encode())
        for name, binary in [('provenance.json', 'loadgen'), ('rust-provenance.json', 'loadgen-rust')]:
            (self.directory / name).write_text(json.dumps({'binary_sha256': bundle.sha(self.directory / binary)}))
        self.manifest = {'sources': bundle.sources(ROOT),
                         'binaries': {n: bundle.sha(self.directory / n) for n in ('loadgen', 'loadgen-rust')},
                         'metadata': {n: bundle.sha(self.directory / n) for n in ('provenance.json', 'rust-provenance.json')}}
        self.write_manifest()

    def write_manifest(self):
        (self.directory / 'generators.json').write_text(json.dumps(self.manifest))

    def test_downloaded_artifact_verified_and_permissions_restored(self):
        bundle.verify(self.directory)
        self.assertEqual((self.directory / 'loadgen-rust').stat().st_mode & 0o777, 0o755)

    def test_tampered_binary_and_metadata_rejected(self):
        for name in ('loadgen', 'loadgen-rust', 'provenance.json', 'rust-provenance.json'):
            p = self.directory / name
            original = p.read_bytes()
            p.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                bundle.verify(self.directory)
            p.write_bytes(original)

    def test_wrong_architecture_or_missing_binary_rejected(self):
        p = self.directory / 'loadgen-rust'
        data = bytearray(p.read_bytes()); data[18:20] = b'\xb7\x00'; p.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'x86_64'):
            bundle.verify(self.directory)
        p.unlink()
        with self.assertRaises(FileNotFoundError):
            bundle.verify(self.directory)

    def test_stale_source_bundle_rejected(self):
        self.manifest['sources']['loadgen-rust/src/main.rs'] = 'stale'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'checked-out sources'):
            bundle.verify(self.directory)

    def test_daily_jobs_share_build_before_aws(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark.yml').read_text())
        jobs = workflow['jobs']; agent = jobs['benchmark']
        self.assertIn('build-generators', agent['needs'])
        steps = agent['steps']
        verify = next(i for i,s in enumerate(steps) if 'generator_bundle.py verify' in s.get('run', ''))
        auth = next(i for i,s in enumerate(steps) if 'configure-aws-credentials' in s.get('uses', ''))
        self.assertLess(verify, auth)
        run = next(s for s in steps if s.get('name') == 'Run isolated agent benchmark')
        self.assertEqual(run['env']['BENCHMARK_PREBUILT_LOADGEN'], '1')
        self.assertFalse(any('setup-go' in s.get('uses','') for s in steps))


class RustDailyPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = fixture.create_fixture(Path(self.tmp.name) / '20260915_091700')
        self.payload = bundle.sha(self.directory / 'fixed-nginx.ndjson')

    def get(self):
        return fixed.tier(self.directory, 'red', 'filter', 10000, self.payload)

    def test_historical_go_and_recorded_rust_require_matching_calibration(self):
        self.assertEqual(self.get()['status'], 'ok')  # Historical Go has no generator identity.
        p = self.directory / 'provenance.json'; provenance = json.loads(p.read_text())
        provenance['fixed_rate']['generator'] = {'generator': 'rust', 'dispatch_mode': 'workers', 'version': 'pipeline-loadgen-rust 0.1.0'}
        p.write_text(json.dumps(provenance))
        self.assertEqual(self.get()['status'], 'invalid')
        p = self.directory / 'red_filter_10000.fixed.json'; raw = json.loads(p.read_text())
        identity = dict(generator='rust', dispatch_mode='workers', generator_version='0.1.0')
        raw['loadgen'].update(identity); p.write_text(json.dumps(raw))
        self.assertEqual(self.get()['status'], 'invalid')  # Calibration still Go.
        c = self.directory / 'red_10000.calibration.json'; cal = json.loads(c.read_text()); cal.update(identity); c.write_text(json.dumps(cal))
        self.assertEqual(self.get()['status'], 'ok')
        import summarize, release_report
        data = summarize.summarize(self.directory)
        self.assertIn('**Fixed-rate load generator:** pipeline-loadgen-rust 0.1.0', (self.directory / 'report.md').read_text())
        self.assertIn('Rust workers (pipeline-loadgen-rust 0.1.0, 256 workers)', release_report.render(data, 'https://example.invalid/run', synthetic=True))
        for key, value in [('dispatch_mode', 'tasks'), ('generator_version', '0.2.0')]:
            changed = copy.deepcopy(raw); changed['loadgen'][key] = value; p.write_text(json.dumps(changed))
            self.assertEqual(self.get()['status'], 'invalid')

    def test_runner_invokes_rust_workers_for_calibration(self):
        # Stop immediately after constructing the first generator command; no service/AWS actions.
        calls = []
        def capture(command, **kwargs):
            calls.append(command)
            if command[0] == 'loadgen-rust':
                raise RuntimeError('captured generator')
        with patch.object(run_fixed.Path, 'mkdir'), patch.object(run_fixed.Path, 'read_bytes', return_value=b'{}\n'), patch.object(run_fixed.Path, 'exists', return_value=False), patch.object(run_fixed.subprocess, 'run', side_effect=capture):
            with self.assertRaisesRegex(RuntimeError, 'captured generator'):
                run_fixed.run('red', 'filter')
        args = calls[-1]
        self.assertEqual(args[args.index('--dispatch-mode') + 1], 'workers')
        self.assertEqual(args[args.index('--workers') + 1], '256')
        self.assertIn('--fixed-calibration', args)
