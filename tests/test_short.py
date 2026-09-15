"""Short profile must exercise recovery without becoming a published benchmark."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import fixed
import parallel
import check_short
import check_results
import preview_release
import publish_release
import yaml

class ShortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = preview_release.create_fixture(Path(self.tmp.name)/'20260915_180000')
        p = self.directory/'provenance.json'; data = json.loads(p.read_text())
        data.update(benchmark_profile='short', duration_per_tier_seconds=10, shards={'red':{}})
        data['fixed_rate']['targets'] = [10000,125000]
        p.write_text(json.dumps(data))

    def test_short_matrix_limits_cases_but_preserves_vendors(self):
        with patch.dict(os.environ, BENCHMARK_PROFILE='short'):
            matrix = parallel.plan('red,vector', 'pass-through,filter,mask,lookup')
        self.assertEqual(matrix, {'include':[{'vendor':'red','cases':'pass-through'},{'vendor':'vector','cases':'pass-through'}]})
        self.assertEqual(fixed.rates_for({'benchmark_profile':'short','schema_version':3}), [10000,125000])
        self.assertEqual(fixed.rates_for({'benchmark_profile':'full','schema_version':3}), [10000,25000,50000,75000,125000])

    def test_short_report_and_recovery_gate(self):
        data = check_short.validate(self.directory)
        self.assertEqual(data['fixed_throughput']['targets'], [10000,125000])
        self.assertIn('SHORT VALIDATION RUN', (self.directory/'report.md').read_text())
        self.assertIn('10 seconds per tier, 5-second drain', (self.directory/'report.md').read_text())
        p=self.directory/'red_pass-through_10000.fixed.json'; raw=json.loads(p.read_text())
        raw['loadgen']['measurement']['acknowledged_logs']-=1
        raw['loadgen']['measurement']['http_status_counts']['200']-=1
        raw['loadgen']['measurement']['errors']=1
        p.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'Rust recovery validation failed'):
            check_short.validate(self.directory)

    def test_short_cannot_publish_even_with_checksums(self):
        (self.directory/'SHA256SUMS').touch()
        with patch.object(publish_release,'gh') as gh:
            with self.assertRaisesRegex(ValueError,'Short validation'):
                publish_release.publish(self.directory, 'unused', 'unused', 'unused')
            gh.assert_not_called()
        with self.assertRaisesRegex(ValueError,'Short validation'):
            check_results.validate(self.directory)
        self.assertFalse((self.directory/'SHA256SUMS').exists())

    def test_profile_is_forwarded_and_workflow_blocks_short_release(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/benchmark.yml').read_text())
        jobs=workflow['jobs']
        step=next(s for s in jobs['benchmark']['steps'] if s.get('name')=='Run isolated agent benchmark')
        self.assertIn('inputs.profile',step['env']['BENCHMARK_PROFILE'])
        steps=jobs['report']['steps'];publish=next(s for s in steps if s.get('name')=='Publish dated release for the full suite')
        self.assertEqual(publish['if'], "inputs.profile != 'short'")
        self.assertIn('BENCHMARK_PROFILE=${BENCHMARK_PROFILE:-full}', (ROOT/'functions.sh').read_text())
        result=subprocess.run([str(ROOT/'run.sh'),'--profile','bogus','--dry-run'],capture_output=True)
        self.assertNotEqual(result.returncode,0)
