import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import agent_versions


def recorder(reply):
    calls = []
    def gh(*args):
        calls.append(args)
        return reply(args) if callable(reply) else reply
    return calls, gh


class AgentVersionResolutionTest(unittest.TestCase):
    def test_vector_picks_newest_stable_semver_release(self):
        releases = [
            {'tag_name': 'v0.61.0', 'draft': True, 'prerelease': False},
            {'tag_name': 'v0.62.0-rc.1', 'draft': False, 'prerelease': True},
            {'tag_name': 'v0.9.0', 'draft': False, 'prerelease': False},
            {'tag_name': 'v0.60.1', 'draft': False, 'prerelease': False},
            {'tag_name': 'nightly', 'draft': False, 'prerelease': False},
            {'tag_name': 'v0.60.0', 'draft': False, 'prerelease': False},
        ]
        calls, gh = recorder(json.dumps(releases))
        self.assertEqual(agent_versions.resolve('vector', gh), ('VECTOR_VERSION', '0.60.1'))
        self.assertEqual(calls[0][0], 'api')
        self.assertIn('repos/vectordotdev/vector/releases?per_page=100', calls[0])

    def test_otelcol_and_fluentd_strip_the_v_prefix(self):
        calls, gh = recorder(json.dumps({'tag_name': 'v0.141.0'}))
        self.assertEqual(agent_versions.resolve('otelcol', gh), ('OTELCOL_VERSION', '0.141.0'))
        self.assertIn('repos/open-telemetry/opentelemetry-collector-releases/releases/latest', calls[0])
        calls, gh = recorder(json.dumps({'tag_name': 'v6.0.5'}))
        self.assertEqual(agent_versions.resolve('fluentd', gh), ('FLUENT_PACKAGE_VERSION', '6.0.5'))
        self.assertIn('repos/fluent/fluent-package-builder/releases/latest', calls[0])

    def test_bindplane_keeps_the_v_prefix_its_asset_names_use(self):
        calls, gh = recorder(json.dumps({'tag_name': 'v1.110.1'}))
        self.assertEqual(agent_versions.resolve('bindplane', gh), ('BINDPLANE_VERSION', 'v1.110.1'))
        self.assertIn('repos/observIQ/bindplane-otel-collector/releases/latest', calls[0])

    def test_rejects_tags_that_are_not_release_versions(self):
        for vendor, tag in [('otelcol', 'latest'), ('bindplane', '1.110.1'), ('fluentd', 'v6.0')]:
            with self.subTest(vendor=vendor):
                _, gh = recorder(json.dumps({'tag_name': tag}))
                with self.assertRaises(ValueError):
                    agent_versions.resolve(vendor, gh)

    def test_main_prints_shell_assignments_and_fails_loudly_when_github_is_down(self):
        with patch.object(agent_versions, 'gh', return_value=json.dumps({'tag_name': 'v0.141.0'})):
            out = io.StringIO()
            with patch('sys.stdout', out):
                self.assertEqual(agent_versions.main(['otelcol']), 0)
            self.assertEqual(out.getvalue(), 'OTELCOL_VERSION=0.141.0\n')
        error = subprocess.CalledProcessError(1, ['gh'], '', 'HTTP 504')
        with patch.object(agent_versions, 'gh', side_effect=error):
            out, err = io.StringIO(), io.StringIO()
            with patch('sys.stdout', out), patch('sys.stderr', err):
                self.assertEqual(agent_versions.main(['otelcol']), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertIn('otelcol', err.getvalue())

    def test_gh_goes_through_the_retrying_runner(self):
        import gh_release
        self.assertIs(agent_versions.gh, gh_release.run)


if __name__ == '__main__':
    unittest.main()
