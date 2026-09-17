"""Synthetic fixtures only: the publication entry point must retain approved styling."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import preview_release
import publish_release
import release_report
import summarize


class ReleaseStyleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = preview_release.create_fixture(Path(self.temp.name)/'20260915_091700')
        self.data = summarize.summarize(self.directory)

    def body(self):
        return publish_release.release_notes((self.directory/'report.md').read_text(), 'https://example.invalid/run', self.data)

    def test_ai_disclosure_is_versioned_and_preserves_fixture_warning(self):
        self.data['provenance']['benchmark_commit'] = 'b' * 40
        before = copy.deepcopy(self.data)
        body = self.body()
        self.assertIn('/blob/' + 'b' * 40 + '/docs/report-prompt.md', body)
        self.assertEqual(body.count('**AI disclosure:**'), 1)
        self.assertLess(body.index('SYNTHETIC FIXTURE'), body.index('**AI disclosure:**'))
        self.assertLess(body.index('**AI disclosure:**'), body.index('**Benchmark date:**'))
        self.assertIn('no AI model writes or modifies the results', body)
        self.assertEqual(self.data, before)
        self.assertTrue((Path(__file__).resolve().parents[1] / 'docs/report-prompt.md').is_file())

    def test_valid_positive_finite_leaders_and_exact_ties(self):
        entries = {name: {'status': status, 'value': value} for name, status, value in [
            ('a', 'ok', 12.1), ('b', 'ok', 12.1), ('rounded', 'ok', 12.09),
            ('error', 'errors', 999), ('failed', 'capacity_limited', 999),
            ('source', 'generator_limited', 999), ('invalid', 'invalid', 999),
            ('missing', 'missing', 999), ('unsupported', 'unsupported', 999),
            ('skipped', 'skipped_after_shortfall', 999), ('nan', 'ok', float('nan')),
            ('inf', 'ok', float('inf')), ('zero', 'ok', 0), ('negative', 'ok', -1), ('none', 'ok', None)]}
        self.assertEqual(release_report.leaders(entries, 'value'), {'a', 'b'})
        self.assertEqual(release_report.leaders({'none': entries['none'], 'zero': entries['zero']}, 'value'), set())

    def test_throughput_ties_and_errors_use_unrounded_measurements(self):
        scenarios = self.data['scenarios']
        scenarios['red/pass-through'].update(avg=100000.2, status='ok')
        scenarios['vector/pass-through'].update(avg=100000.2, status='ok')
        scenarios['fluentd/pass-through'].update(avg=100000.1, status='ok')
        scenarios['edgedelta/pass-through'].update(avg=999999, status='errors')
        overview = self.body().split('## Best-tested throughput')[1].split('## Highest sustained')[0]
        self.assertIn('| 🏆 **Vector** | **100,000** |', overview)
        self.assertIn('| 🏆 **Edge Delta (Rust)** | **100,000** |', overview)
        self.assertIn('| 🏆 **Fluentd** | 100,000 |', overview)
        self.assertIn('| 🏆 **Edge Delta (Go)** | 999,999 † |', overview)
        self.assertLess(overview.index('**Fluentd** |'), overview.index('**Edge Delta (Go)** |'))

    def test_fixed_highlights_ties_and_sole_pass_but_never_failed_rows(self):
        tiers = self.data['fixed_throughput']['tiers']
        for vendor in summarize.VENDORS:
            tiers[f'{vendor}/filter/10000'].update(status='capacity_limited', logs_per_second_per_core=999999999)
        tiers['red/filter/10000'].update(status='ok', logs_per_second_per_core=123456.2)
        tiers['vector/filter/10000'].update(status='ok', logs_per_second_per_core=123456.2)
        before = copy.deepcopy(self.data)
        body = self.body()
        self.assertEqual(self.data, before)
        section = body.split('### Filter —')[1].split('### Mask —')[0]
        highlighted = [r for r in section.splitlines() if r.startswith('| **10,000**')]
        self.assertEqual(len(highlighted), 2)
        self.assertTrue(all('**Pass**' in row for row in highlighted))
        self.assertIn('🔹 **Edge Delta (Rust)**', highlighted[0])
        self.assertIn('🔹 **Vector**', highlighted[1])
        self.assertNotIn('**Fail', body)
        tiers['vector/filter/10000']['status'] = 'generator_limited'
        section = self.body().split('### Filter —')[1].split('### Mask —')[0]
        self.assertEqual(len([r for r in section.splitlines() if r.startswith('| **10,000**')]), 1)
        tiers['red/filter/10000']['status'] = 'invalid'
        section = self.body().split('### Filter —')[1].split('### Mask —')[0]
        self.assertNotIn('| **10,000**', section)

    def test_target_tie_breaks_use_remaining_scenarios_without_inventing_wins(self):
        tiers = self.data['fixed_throughput']['tiers']
        for t in tiers.values():
            if t['status'] != 'unsupported': t['status'] = 'capacity_limited'
        for v in ['red', 'vector']:
            tiers[f'{v}/pass-through/125000']['status'] = 'ok'
        tiers['vector/filter/75000']['status'] = 'ok'
        section = self.body().split('## Highest sustained fixed-rate target')[1].split('## Hardware')[0]
        self.assertLess(section.index('**Vector**'), section.index('**Edge Delta (Rust)**'))
        self.assertEqual(section.count('**125,000**'), 2)
        self.assertNotIn('**None**', section)
        self.assertNotIn('**Unsupported**', section)

    def test_unverified_environment_and_history_keep_qualifications(self):
        self.data['fixed_throughput']['matching_environment'] = False
        self.assertIn('equal machine/process limits could not be fully verified', self.body())
        self.data['fixed_throughput']['measured'] = False
        body = self.body()
        self.assertNotIn('🔹', body)
        self.assertNotIn('## Highest sustained', body)
        self.assertIn('not measured in this historical result format', body)
