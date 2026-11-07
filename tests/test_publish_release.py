import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import publish_release as publisher


def graphql(release):
    return json.dumps({'data': {'repository': {'release': release}}})


def fake_gh(calls, existing=None, created_id=1, assets=None):
    """Answer the by-id publication flow: GraphQL lookup, POST create, asset listing."""
    def gh(*args):
        calls.append(args)
        if args[:2] == ('api', 'graphql'):
            return graphql(existing)
        if args[:3] == ('api', '--method', 'POST') and args[3].endswith('/releases'):
            return json.dumps({'id': created_id, 'html_url': 'https://example.invalid/release'})
        if args[0] == 'api' and '/assets?' in args[-1]:
            return json.dumps(assets or [[]])
        return ''
    return gh


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
            calls = []
            gh = fake_gh(calls, assets=[[{'name': 'report.md', 'digest': 'sha256:' + '0' * 64}]])
            with patch.object(publisher, 'validate', return_value=data), patch.object(publisher, 'gh', side_effect=gh):
                with self.assertRaisesRegex(ValueError, 'assets differ'):
                    publisher.publish(path, 'owner/repo', 'a' * 40, 'https://example.com/run')
            self.assertFalse(any('PATCH' in c for c in calls))

    def test_release_notes_preserve_performance(self):
        report = ('## Benchmark Scenario: Filter\n\n### Performance Comparison\n\n81,399 logs/sec\n\n'
                  '### Reliability Comparison\n\nerrors\n\n### Connection Recovery (all tiers)\n\nretries\n\n'
                  '## Cross-Scenario Summary\n\nresults\n')
        notes = publisher.release_notes(report, 'https://example.com/run')
        self.assertIn('81,399 logs/sec', notes)
        self.assertIn('Cross-Scenario Summary', notes)
        self.assertIn('Connection', notes)
        self.assertIn('Reliability', notes)
        self.assertTrue(notes.startswith('> **Impartial analysis and transparency:**'))
        self.assertIn('/blob/main/docs/report-prompt.md', notes)

    def test_large_asset_set_is_uploaded_and_verified_by_id_without_listing_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'20260915_091700';path.mkdir()
            for i in range(170):(path/f'asset-{i}.json').write_text('{}')
            (path/'report.md').write_text('## Hardware and environment specifications\nReal renderer is tested separately.')
            assets=sorted(path.glob('asset-*.json'))
            (path/'SHA256SUMS').write_text(''.join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets))
            assets.append(path/'SHA256SUMS')
            remote=[{'name':p.name,'digest':'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets]
            calls=[]
            gh=fake_gh(calls, created_id=1, assets=[remote[:100],remote[100:]])
            data={'scenarios':{'red/filter':{'status':'ok'},'fluentd/filter':{'status':'errors','workers':[{'errors':27850}]}},'provenance':{'benchmark_commit':'a'*40}}
            with patch.object(publisher,'validate',return_value=data),patch.object(publisher,'gh',side_effect=gh):publisher.publish(path,'owner/repo','a'*40,'https://example.invalid/run')
            # Never list every release: that response embeds every asset of every release.
            self.assertFalse(any(c[-1].endswith('repos/owner/repo/releases') and '--paginate' in c for c in calls))
            self.assertFalse(any(c[0]=='release' for c in calls))
            uploads=[c for c in calls if 'https://uploads.github.com/repos/owner/repo/releases/1/assets?name=' in ' '.join(c)]
            self.assertEqual(len(uploads),171)
            created = next(c for c in calls if c[:3] == ('api', '--method', 'POST') and c[3].endswith('/releases'))
            self.assertIn('name=Benchmark Report - 20260915-091700', created)
            self.assertIn('draft=true', created)
            self.assertTrue(any('/releases/1/assets?per_page=100' in c[-1] for c in calls))
            self.assertIn('PATCH',calls[-1])
            self.assertIn('repos/owner/repo/releases/1', calls[-1])
            self.assertIn('make_latest=true', calls[-1])

    def test_leftover_draft_is_replaced_on_rerun(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'20260915_091700';path.mkdir()
            (path/'report.md').write_text('performance')
            (path/'SHA256SUMS').write_text(f"{hashlib.sha256(b'performance').hexdigest()}  report.md\n")
            remote=[{'name':n,'digest':'sha256:'+hashlib.sha256((path/n).read_bytes()).hexdigest()} for n in ['report.md','SHA256SUMS']]
            calls=[]
            stale={'databaseId':77,'isDraft':True,'url':'https://example.invalid/stale'}
            gh=fake_gh(calls, existing=stale, created_id=78, assets=[remote])
            data={'scenarios':{'red/filter':{'status':'ok'}},'provenance':{'benchmark_commit':'a'*40}}
            with patch.object(publisher,'validate',return_value=data),patch.object(publisher,'gh',side_effect=gh):publisher.publish(path,'owner/repo','a'*40,'https://example.invalid/run')
            deleted=[c for c in calls if c[:3]==('api','--method','DELETE')]
            self.assertEqual(len(deleted),1)
            self.assertIn('repos/owner/repo/releases/77', deleted[0])
            self.assertIn('repos/owner/repo/releases/78', calls[-1])
            self.assertIn('PATCH', calls[-1])

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
            existing={'databaseId':3,'isDraft':False,'url':'https://example.invalid/release'}
            with patch.object(publisher,'validate',return_value=data),patch.object(publisher,'gh',return_value=graphql(existing)) as gh:publisher.publish(path,'owner/repo','a'*40,'https://example.invalid/run')
            self.assertEqual(gh.call_count,1)
