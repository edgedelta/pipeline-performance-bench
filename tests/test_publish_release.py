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

    def test_invalid_suite_never_contacts_github(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(publisher, 'gh') as gh:
            path = Path(temp); (path / 'SHA256SUMS').touch()
            with patch.object(publisher, 'validate', side_effect=ValueError('invalid measurement evidence')):
                with self.assertRaisesRegex(ValueError, 'invalid measurement'):
                    publisher.publish(path, 'owner/repo', 'a' * 40, 'https://example.com/run')
            gh.assert_not_called()

    def test_bad_asset_digest_leaves_draft_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '20260915_091700'; path.mkdir()
            (path / 'SHA256SUMS').write_text('unused  report.md\n')
            (path / 'report.md').write_text('performance')
            data = {'scenarios': {'red/filter': {'status': 'ok'}}, 'provenance': {'benchmark_commit': 'a' * 40}}
            responses = [json.dumps([[]]), '', '', json.dumps([[{'id': 1, 'tag_name': '20260915-091700', 'assets': [], 'html_url': 'url'}]]), json.dumps([[]])]
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
        self.assertIn('Connection', notes)
        self.assertIn('Reliability', notes)
        self.assertTrue(notes.startswith('> **AI disclosure:**'))
        self.assertIn('/blob/main/docs/report-prompt.md', notes)

    def test_large_asset_set_is_paginated_and_verified_before_publish(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'20260915_091700';path.mkdir()
            for i in range(170):(path/f'asset-{i}.json').write_text('{}')
            (path/'report.md').write_text('## Hardware and environment specifications\nReal renderer is tested separately.')
            assets=sorted(path.glob('asset-*.json'))
            (path/'SHA256SUMS').write_text(''.join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets))
            assets.append(path/'SHA256SUMS')
            remote=[{'name':p.name,'digest':'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets]
            release={'id':1,'tag_name':'20260915-091700','html_url':'https://example.invalid/release','draft':True,'assets':remote[:30]}
            calls=[];listing=0
            def gh(*args):
                nonlocal listing
                calls.append(args)
                if args[0]=='api' and args[-1]=='repos/owner/repo/releases':
                    listing+=1
                    return json.dumps([[]] if listing==1 else [[release]])
                if args[0]=='api' and '/assets?' in args[-1]:return json.dumps([remote[:100],remote[100:]])
                return ''
            data={'scenarios':{'red/filter':{'status':'ok'},'fluentd/filter':{'status':'errors','workers':[{'errors':27850}]}},'provenance':{'benchmark_commit':'a'*40}}
            with patch.object(publisher,'validate',return_value=data),patch.object(publisher,'gh',side_effect=gh):publisher.publish(path,'owner/repo','a'*40,'https://example.invalid/run')
            uploads=[c for c in calls if c[:2]==('release','upload')]
            self.assertEqual(len(uploads),9)
            created = next(c for c in calls if c[:2] == ('release', 'create'))
            self.assertEqual(created[created.index('--title')+1], 'Benchmark Report - 20260915-091700')
            self.assertTrue(any('/assets?per_page=100' in c[-1] for c in calls))
            self.assertIn('PATCH',calls[-1])

    def test_error_outcomes_are_explicit_in_release_intro(self):
        data={'scenarios':{'fluentd/filter':{'status':'errors','workers':[{'errors':0},{'errors':0},{'errors':27850}]}}}
        notes=publisher.release_notes('Retained report','https://example.invalid/run',data)
        self.assertIn('1 scenario(s) recorded 27,850 unrecovered request errors',notes)
        self.assertIn('excluded from throughput rankings',notes)
        self.assertIn('Retained report',notes)

    def test_existing_published_release_is_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'20260915_091700';path.mkdir();(path/'SHA256SUMS').touch()
            data={'scenarios':{'red/filter':{'status':'ok'}},'provenance':{'benchmark_commit':'a'*40}}
            existing={'tag_name':'20260915-091700','draft':False,'html_url':'https://example.invalid/release'}
            with patch.object(publisher,'validate',return_value=data),patch.object(publisher,'gh',return_value=json.dumps([[existing]])) as gh:publisher.publish(path,'owner/repo','a'*40,'https://example.invalid/run')
            self.assertEqual(gh.call_count,1)
