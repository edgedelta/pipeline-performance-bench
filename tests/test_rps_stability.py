import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from otlpbench import readiness


def listening_server():
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(16)
    def accept():
        while True:
            try: conn, _ = server.accept()
            except OSError: return
            conn.close()
    threading.Thread(target=accept, daemon=True).start()
    return server, server.getsockname()[1]


def free_port():
    """A port nothing listens on: bound and released without ever listening, so no thread holds it open."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class LocalHost:
    """Runs the probe locally instead of over ssh; records the argv it was given."""
    def __init__(self): self.calls = []
    def argv(self, args):
        self.calls.append(args)
        return subprocess.check_output(args, text=True)


class ReadinessProbeTest(unittest.TestCase):
    def test_probe_reports_ready_once_port_accepts_for_stability_window(self):
        server, port = listening_server()
        try:
            out = json.loads(subprocess.check_output([sys.executable, '-c', readiness.PROBE, '127.0.0.1', str(port), '2', '10'], text=True))
        finally:
            server.close()
        self.assertTrue(out['ready'])
        self.assertGreaterEqual(out['successes'], 2)
        self.assertEqual(out['failures'], 0)
        self.assertGreaterEqual(out['seconds'], 1)

    def test_probe_reports_not_ready_when_nothing_listens(self):
        port = free_port()
        out = json.loads(subprocess.check_output([sys.executable, '-c', readiness.PROBE, '127.0.0.1', str(port), '2', '2'], text=True))
        self.assertFalse(out['ready'])
        self.assertEqual(out['successes'], 0)
        self.assertGreaterEqual(out['failures'], 1)

    def test_wait_reachable_runs_probe_on_given_host(self):
        server, port = listening_server()
        host = LocalHost()
        try:
            out = readiness.wait_reachable(host, '127.0.0.1', port, stable=2, timeout=10)
        finally:
            server.close()
        self.assertTrue(out['ready'])
        self.assertEqual(len(host.calls), 1)
        self.assertEqual(host.calls[0][:3], ['python3', '-c', readiness.PROBE])
        self.assertEqual(host.calls[0][3:], ['127.0.0.1', str(port), '2', '10'])


class RetryPolicyTest(unittest.TestCase):
    def test_only_infrastructure_failures_retry_and_only_once(self):
        for status in ['execution_failed', 'agent_unreachable']:
            self.assertTrue(readiness.should_retry(status, attempt=0), status)
            self.assertFalse(readiness.should_retry(status, attempt=1), status)
        for status in ['measured', 'input_shortfall', 'operation_mismatch', 'batch_mismatch', 'warmup_failed', 'harness_limited']:
            self.assertFalse(readiness.should_retry(status, attempt=0), status)


class RetryOrchestrationTest(unittest.TestCase):
    def run_attempts(self, outcomes):
        import tempfile
        calls = []
        def measure():
            status = outcomes[len(calls)]
            calls.append(status)
            (self.out / 'otelcol-512-2000-0-agent.log').write_text(f'log of attempt {len(calls)}')
            return {'vendor': 'otelcol', 'status': status}
        self.tmp = tempfile.TemporaryDirectory(); self.out = Path(self.tmp.name)
        report, saves = {'rows': []}, []
        readiness.run_attempts(measure, self.out / 'otelcol-512-2000-0', report, lambda: saves.append(len(report['rows'])))
        return calls, report, saves

    def test_measured_row_is_recorded_once_with_attempt_count(self):
        calls, report, saves = self.run_attempts(['measured'])
        self.assertEqual(calls, ['measured'])
        self.assertEqual(report['rows'], [{'vendor': 'otelcol', 'status': 'measured', 'attempts': 1}])
        self.assertNotIn('retried', report)
        self.assertEqual(saves, [1])

    def test_infrastructure_failure_retries_once_and_keeps_first_attempt_evidence(self):
        calls, report, saves = self.run_attempts(['execution_failed', 'measured'])
        self.assertEqual(calls, ['execution_failed', 'measured'])
        self.assertEqual(report['rows'], [{'vendor': 'otelcol', 'status': 'measured', 'attempts': 2}])
        self.assertEqual(report['retried'], [{'vendor': 'otelcol', 'status': 'execution_failed', 'attempt': 0}])
        self.assertEqual((self.out / 'otelcol-512-2000-0-attempt0-agent.log').read_text(), 'log of attempt 1')
        self.assertEqual((self.out / 'otelcol-512-2000-0-agent.log').read_text(), 'log of attempt 2')
        self.assertEqual(saves, [0, 1])

    def test_second_infrastructure_failure_is_recorded_not_retried_again(self):
        calls, report, saves = self.run_attempts(['agent_unreachable', 'agent_unreachable', 'measured'])
        self.assertEqual(calls, ['agent_unreachable', 'agent_unreachable'])
        self.assertEqual(report['rows'], [{'vendor': 'otelcol', 'status': 'agent_unreachable', 'attempts': 2}])
        self.assertEqual(len(report['retried']), 1)

    def test_result_statuses_are_never_retried(self):
        calls, report, saves = self.run_attempts(['input_shortfall', 'measured'])
        self.assertEqual(calls, ['input_shortfall'])
        self.assertEqual(report['rows'][0]['status'], 'input_shortfall')
        self.assertNotIn('retried', report)


class SetupApiRetryTest(unittest.TestCase):
    def test_failing_setup_api_calls_retry_transient_errors(self):
        root = Path(__file__).resolve().parents[1]
        for script in ['pipelines/edgedelta/edgedelta-api.sh', 'pipelines/cribl/cribl-api.sh']:
            text = (root / script).read_text()
            calls = [c for c in text.split('curl')[1:] if c.lstrip().startswith(('-fsS', '--fail'))]
            self.assertTrue(calls, script)
            for call in calls:
                head = call.split('\\\n')[0] if '\\\n' in call else call.split('\n')[0]
                self.assertIn('${CURL_RETRY[@]}', head, f'{script}: {head.strip()[:60]}')
            # curl exit 92 (HTTP/2 stream reset after a 57 s deploy) killed the 10 Nov edgedelta
            # job: force HTTP/1.1 and retry every error, not only transient HTTP codes.
            self.assertIn('CURL_RETRY=(--http1.1 --retry 3 --retry-delay 5 --retry-connrefused --retry-all-errors)', text, script)


if __name__ == '__main__':
    unittest.main()
