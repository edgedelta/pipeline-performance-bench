"""Exercise the provisioning script without sudo, apt, network or AWS changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BootstrapTest(unittest.TestCase):
    def run_script(self, mode='success', cloud_status=0):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); binary=root/'bin';binary.mkdir(); log=root/'calls'; state=root/'attempts'
            mocks={
                'sudo': 'printf "sudo %s\\n" "$*" >> "$CALLS"\ncase "$1" in timeout) exit "$CLOUD_STATUS";; tee) cat >/dev/null;; install) exit 0;; *) exec "$@";; esac\n',
                'apt-get': 'printf "apt %s\\n" "$*" >> "$CALLS"\nif [[ "$1" == update ]]; then\n n=0; [[ ! -f "$STATE" ]] || n=$(cat "$STATE"); n=$((n+1)); echo "$n" > "$STATE"\n case "$MODE" in lock) if [[ "$n" -lt 3 ]]; then echo "E: Could not get lock /var/lib/apt/lists/lock" >&2; exit 100; fi;; permanent-lock) echo "E: Could not get lock /var/lib/apt/lists/lock" >&2; exit 100;; repository-error) echo "E: repository has no Release file" >&2; exit 100;; esac\nfi\n',
                'sleep': 'echo "sleep $*" >> "$CALLS"\n',
                'loadgen': 'echo "loadgen $*" >> "$CALLS"\n',
                'rm': 'if [[ "$1" != /tmp/benchmark-loadgen ]]; then /bin/rm "$@"; fi\n',
            }
            for name, body in mocks.items():
                p=binary/name;p.write_text('#!/usr/bin/env bash\n'+body);p.chmod(0o755)
            # Run the real script; redirect only its harmless output directory away from ~.
            script=(ROOT/'scripts/install_loadgen.sh').read_text().replace('mkdir -p ~/benchmark_scripts','mkdir -p ./benchmark_scripts')
            result=subprocess.run(['bash','-c',script],cwd=tmp,env=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],CALLS=str(log),STATE=str(state),MODE=mode,CLOUD_STATUS=str(cloud_status)),text=True,capture_output=True)
            return result,log.read_text(),int(state.read_text()) if state.exists() else 0

    def test_waits_for_boot_before_install_and_sets_package_lock_timeout(self):
        result,calls,count=self.run_script()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLess(calls.index('timeout 600 cloud-init status --wait'),calls.index('apt update'))
        self.assertIn('tee /etc/apt/apt.conf.d/99benchmark-lock-wait',calls)
        self.assertIn('apt -o DPkg::Lock::Timeout=600 install',calls)
        self.assertEqual(count,1)

    def test_transient_lists_lock_recovers(self):
        result,calls,count=self.run_script('lock')
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(count,3);self.assertEqual(calls.count('sleep 5'),2)

    def test_persistent_lock_is_bounded_and_stops_install(self):
        result,calls,count=self.run_script('permanent-lock')
        self.assertEqual(result.returncode,100);self.assertEqual(count,12);self.assertEqual(calls.count('sleep 5'),11);self.assertNotIn('loadgen --help',calls)

    def test_repository_error_is_not_retried(self):
        result,calls,count=self.run_script('repository-error')
        self.assertEqual(result.returncode,100);self.assertEqual(count,1);self.assertNotIn('sleep 5',calls)

    def test_failed_or_timed_out_cloud_init_stops_before_apt(self):
        for status in [1,2,124]:
            with self.subTest(status=status):
                result,calls,count=self.run_script(cloud_status=status)
                self.assertEqual(result.returncode,status);self.assertEqual(count,0);self.assertNotIn('apt update',calls)
