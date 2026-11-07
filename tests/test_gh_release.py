import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gh_release


def completed(code, out='', err=''):
    return subprocess.CompletedProcess(['gh'], code, out, err)


class RetryingRunnerTest(unittest.TestCase):
    def test_retries_transient_github_errors(self):
        outcomes = [completed(1, '', 'gh: We couldn\'t respond to your request in time. (HTTP 504)'),
                    completed(1, '', 'gh: connection reset by peer'),
                    completed(0, '{"ok": true}')]
        sleeps = []
        with patch.object(gh_release.subprocess, 'run', side_effect=outcomes) as run:
            out = gh_release.run('api', 'x', sleep=sleeps.append)
        self.assertEqual(out, '{"ok": true}')
        self.assertEqual(run.call_count, 3)
        self.assertEqual(len(sleeps), 2)

    def test_does_not_retry_client_errors(self):
        with patch.object(gh_release.subprocess, 'run', return_value=completed(1, '', 'HTTP 422: Validation Failed')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                gh_release.run('api', 'x', sleep=lambda s: None)
        self.assertEqual(run.call_count, 1)

    def test_gives_up_after_three_attempts(self):
        with patch.object(gh_release.subprocess, 'run', return_value=completed(1, '', 'HTTP 502')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                gh_release.run('api', 'x', sleep=lambda s: None)
        self.assertEqual(run.call_count, 3)


class ByIdHelpersTest(unittest.TestCase):
    def recorder(self, reply):
        calls = []
        def gh(*args):
            calls.append(args)
            return reply(args) if callable(reply) else reply
        return calls, gh

    def test_find_release_queries_graphql_by_tag_and_sees_drafts(self):
        body = {'data': {'repository': {'release': {'databaseId': 437502212, 'isDraft': True, 'url': 'https://example.invalid/r'}}}}
        calls, gh = self.recorder(json.dumps(body))
        found = gh_release.find_release(gh, 'owner/repo', '20261107-092008')
        self.assertEqual(found, {'id': 437502212, 'draft': True, 'html_url': 'https://example.invalid/r'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ('api', 'graphql'))
        self.assertIn('tag=20261107-092008', calls[0])
        self.assertIn('owner=owner', calls[0])
        self.assertIn('name=repo', calls[0])
        self.assertFalse(any(a.endswith('repos/owner/repo/releases') for a in calls[0]))

    def test_find_release_returns_none_for_missing_tag(self):
        calls, gh = self.recorder(json.dumps({'data': {'repository': {'release': None}}}))
        self.assertIsNone(gh_release.find_release(gh, 'owner/repo', 'nope'))

    def test_create_draft_returns_id_from_post_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / 'notes.md'
            notes.write_text('body')
            calls, gh = self.recorder(json.dumps({'id': 5, 'html_url': 'https://example.invalid/5'}))
            release = gh_release.create_draft(gh, 'owner/repo', 'tag-1', 'a' * 40, 'Title', notes)
        self.assertEqual(release, {'id': 5, 'draft': True, 'html_url': 'https://example.invalid/5'})
        args = calls[0]
        self.assertEqual(args[:3], ('api', '--method', 'POST'))
        self.assertIn('repos/owner/repo/releases', args)
        self.assertIn('tag_name=tag-1', args)
        self.assertIn('target_commitish=' + 'a' * 40, args)
        self.assertIn('name=Title', args)
        self.assertIn('draft=true', args)
        self.assertIn(f'body=@{notes}', args)

    def test_upload_assets_posts_each_file_to_the_release_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in ['b.json', 'a.json']:
                p = Path(tmp) / name
                p.write_text(name)
                paths.append(p)
            calls, gh = self.recorder('{}')
            gh_release.upload_assets(gh, 'owner/repo', 5, paths)
        self.assertEqual(len(calls), 2)
        for args, p in zip(calls, paths):
            self.assertEqual(args[:3], ('api', '--method', 'POST'))
            self.assertIn(f'https://uploads.github.com/repos/owner/repo/releases/5/assets?name={p.name}', args)
            self.assertIn(str(p), args)
            self.assertIn('--input', args)
            self.assertIn('Content-Type: application/octet-stream', args)

    def test_remote_digests_paginates_assets_by_id(self):
        pages = [[{'name': 'a', 'digest': 'sha256:1'}], [{'name': 'b', 'digest': 'sha256:2'}]]
        calls, gh = self.recorder(json.dumps(pages))
        self.assertEqual(gh_release.remote_digests(gh, 'owner/repo', 5), {'a': 'sha256:1', 'b': 'sha256:2'})
        self.assertIn('--paginate', calls[0])
        self.assertIn('repos/owner/repo/releases/5/assets?per_page=100', calls[0])

    def test_publish_and_delete_address_the_release_id(self):
        calls, gh = self.recorder('')
        gh_release.mark_published(gh, 'owner/repo', 5, make_latest=False)
        gh_release.delete_release(gh, 'owner/repo', 5)
        self.assertEqual(calls[0][:3], ('api', '--method', 'PATCH'))
        self.assertIn('repos/owner/repo/releases/5', calls[0])
        self.assertIn('draft=false', calls[0])
        self.assertIn('make_latest=false', calls[0])
        self.assertEqual(calls[1][:3], ('api', '--method', 'DELETE'))
        self.assertIn('repos/owner/repo/releases/5', calls[1])


if __name__ == '__main__':
    unittest.main()
