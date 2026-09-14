import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import publish_release as publisher


class PublicationTest(unittest.TestCase):
    def test_partial_suite_never_contacts_github(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(publisher, 'gh') as gh:
            publisher.publish(temp, 'owner/repo', 'a' * 40, 'https://example.com/run')
            gh.assert_not_called()

    def test_failed_suite_never_contacts_github(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(publisher, 'gh') as gh:
            path = Path(temp); (path / 'SHA256SUMS').touch()
            with patch.object(publisher, 'validate', return_value={'scenarios': {'red/filter': {'status': 'errors'}}}):
                with self.assertRaisesRegex(ValueError, 'successful'):
                    publisher.publish(path, 'owner/repo', 'a' * 40, 'https://example.com/run')
            gh.assert_not_called()

    def test_bad_asset_digest_leaves_draft_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '20260915_091700'; path.mkdir()
            (path / 'SHA256SUMS').write_text('unused  report.md\n')
            (path / 'report.md').write_text('performance')
            data = {'scenarios': {'red/filter': {'status': 'ok'}}, 'provenance': {'benchmark_commit': 'a' * 40}}
            responses = [json.dumps([[]]), '', '', json.dumps([[{'id': 1, 'tag_name': '20260915-091700', 'assets': [], 'html_url': 'url'}]])]
            with patch.object(publisher, 'validate', return_value=data), patch.object(publisher, 'gh', side_effect=responses) as gh:
                with self.assertRaisesRegex(ValueError, 'assets differ'):
                    publisher.publish(path, 'owner/repo', 'a' * 40, 'https://example.com/run')
                self.assertFalse(any('PATCH' in c.args for c in gh.call_args_list))

    def test_release_notes_preserve_performance(self):
        report = ('## Benchmark Scenario: Filter\n\n### Performance Comparison\n\n81,399 logs/sec\n\n'
                  '### Reliability Comparison\n\nerrors\n\n### Connection Recovery (all tiers)\n\nretries\n\n'
                  '## Cross-Scenario Summary\n\nresults\n')
        notes = publisher.release_notes(report, 'https://example.com/run')
        self.assertIn('81,399 logs/sec', notes)
        self.assertIn('Cross-Scenario Summary', notes)
        self.assertNotIn('Connection', notes)
        self.assertNotIn('Reliability', notes)
