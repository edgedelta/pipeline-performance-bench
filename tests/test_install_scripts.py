"""The agent install scripts must survive a GitHub incident.

On 8 Nov 2026 nine jobs died within seven seconds of GitHub returning HTTP 504:
curl's default three retries back off 1, 2 and 4 seconds. The scripts now take a
version resolved on the runner (authenticated gh, which that incident did not
affect) and only fall back to api.github.com themselves, and every GitHub curl
has a retry budget measured in minutes rather than seconds.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'

CURL_STUB = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CURL_LOG"
url=""; out=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[i]}" in
    http*) url=${args[i]} ;;
    -o) out=${args[i+1]} ;;
    -O) out=$(basename "${args[i+1]:-x}") ;;
  esac
done
if [[ $url == *api.github.com/repos/vectordotdev/vector* ]]; then
  printf '%s' '[{"tag_name":"v0.60.1","draft":false,"prerelease":false},{"tag_name":"v0.61.0-rc.1","draft":false,"prerelease":true},{"tag_name":"v0.9.0","draft":false,"prerelease":false}]'
elif [[ $url == *api.github.com/repos/observIQ* ]]; then
  printf '%s' '{"tag_name":"v1.110.1"}'
elif [[ $url == *api.github.com/repos/open-telemetry* ]]; then
  printf '%s' '{"tag_name":"v0.141.0"}'
elif [[ $url == *api.github.com/repos/fluent* ]]; then
  printf '%s' '{"tag_name":"v6.0.5"}'
elif [[ -n $out ]]; then
  : > "$out"
fi
'''

VENDORS = {
    'vector': ('VECTOR_VERSION', '0.60.1', 'https://github.com/vectordotdev/vector/releases/download/v0.60.1/'),
    'otelcol': ('OTELCOL_VERSION', '0.141.0', 'releases/download/v0.141.0/otelcol-contrib_0.141.0_linux_amd64.deb'),
    'bindplane': ('BINDPLANE_VERSION', 'v1.110.1', 'releases/download/v1.110.1/observiq-otel-collector_v1.110.1_linux_amd64.deb'),
    'fluentd': ('FLUENT_PACKAGE_VERSION', '6.0.5', 'install-ubuntu-noble-fluent-package6-lts.sh'),
}


@unittest.skipUnless(shutil.which('jq'), 'jq is needed by the install scripts')
class InstallScriptTest(unittest.TestCase):
    def run_script(self, vendor, env_version=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            stubs = tmp / 'bin'; stubs.mkdir()
            (stubs / 'curl').write_text(CURL_STUB)
            for name in ['sudo', 'sh', 'tar', 'dpkg', 'systemctl', 'sha256sum', 'install']:
                (stubs / name).write_text('#!/usr/bin/env bash\ncat >/dev/null 2>&1 || true\nexit 0\n')
            for p in stubs.iterdir():
                p.chmod(0o755)
            log = tmp / 'curl.log'; log.touch()
            env = {'PATH': f'{stubs}:{os.environ["PATH"]}', 'HOME': str(tmp), 'CURL_LOG': str(log), 'TMPDIR': str(tmp)}
            if env_version:
                env[VENDORS[vendor][0]] = env_version
            script = (SCRIPTS / f'install_agent_{vendor}.sh').read_text()
            proc = subprocess.run(['bash', '-s'], input=script, text=True, env=env, cwd=tmp, capture_output=True)
            return log.read_text().splitlines(), proc

    def test_runner_resolved_version_skips_api_github_com(self):
        for vendor, (_, version, download) in VENDORS.items():
            with self.subTest(vendor=vendor):
                calls, _ = self.run_script(vendor, env_version=version)
                self.assertTrue(calls, 'script never reached curl')
                self.assertFalse(any('api.github.com' in c for c in calls), calls)
                self.assertTrue(any(download in c for c in calls), calls)

    def test_without_a_resolved_version_the_host_asks_api_github_com(self):
        for vendor, (_, version, download) in VENDORS.items():
            with self.subTest(vendor=vendor):
                calls, _ = self.run_script(vendor)
                self.assertTrue(any('api.github.com' in c for c in calls), calls)
                self.assertTrue(any(download in c for c in calls), calls)

    def test_every_curl_has_a_retry_budget_measured_in_minutes(self):
        for vendor in VENDORS:
            with self.subTest(vendor=vendor):
                calls, _ = self.run_script(vendor)
                for call in calls:
                    retries = int(re.search(r'--retry (\d+)', call).group(1))
                    delay = int(re.search(r'--retry-delay (\d+)', call).group(1))
                    self.assertGreaterEqual(retries * delay, 120, call)
                    self.assertIn('--retry-connrefused', call)


class HarnessPlumbingTest(unittest.TestCase):
    def test_otlp_install_script_downloads_with_the_same_budget(self):
        text = (ROOT / 'otlpbench' / 'install.sh').read_text()
        for line in text.splitlines():
            if 'curl ' in line and 'github.com' in line:
                self.assertIn('"${retry[@]}"', line, line)
        self.assertRegex(text, r'retry=\(--retry (\d+) --retry-delay (\d+) --retry-connrefused\)')

    def test_otlp_agent_host_pins_bindplane_through_the_environment(self):
        text = (ROOT / 'otlpbench' / 'cloud_rps.py').read_text()
        self.assertNotIn("sed -i '/^version=/", text)
        self.assertIn('BINDPLANE_VERSION=v1.110.1 bash otlpbench/install.sh bindplane', text)

    def test_logs_harness_resolves_versions_on_the_runner_and_forwards_them(self):
        functions = (ROOT / 'functions.sh').read_text()
        self.assertIn('${AGENT_ENV:+$AGENT_ENV }bash -se', functions)
        self.assertIn('tools/agent_versions.py', functions)
        run = (ROOT / 'run.sh').read_text()
        for vendor in VENDORS:
            self.assertIn(f'AGENT_ENV=$(resolve_agent_version {vendor}) run_scripts_on_ec2_instance "$runtime_dir/scripts/install_agent_{vendor}.sh"', run)


if __name__ == '__main__':
    unittest.main()
