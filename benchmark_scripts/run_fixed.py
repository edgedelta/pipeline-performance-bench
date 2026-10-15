#!/usr/bin/env python3
"""Run measured fixed-rate tiers on the currently installed scenario configuration."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import socket
import hashlib
import fixed
import collect_machine

SERVICES = {'bindplane': ('observiq-otel-collector.service', 9085), 'edgedelta': ('edgedelta.service', 8085), 'red': ('red.service', 7085), 'cribl': ('cribl-edge.service', 6085), 'otelcol': ('otelcol-contrib.service', 5085), 'fluentd': ('fluentd.service', 3085), 'vector': ('vector.service', 4085), 'fluentbit': ('fluent-bit.service', 2085)}
RATES = fixed.rates_for({"schema_version": 3, "benchmark_profile": os.environ.get("BENCHMARK_PROFILE", "full")})


def systemctl(*args):
    return subprocess.check_output(['systemctl', *args], text=True).strip()


def ready(service, port):
    stable = 0
    previous = None
    for _ in range(300):
        current = systemctl('show', service, '-p', 'InvocationID', '--value')
        active = systemctl('show', service, '-p', 'ActiveState', '--value') == 'active'
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1): listening = True
        except OSError: listening = False
        stable = stable + 1 if listening and active and current and current == previous else 0
        if stable >= 30: return current
        previous = current; time.sleep(1)
    raise RuntimeError('Service did not remain active for 30 seconds')


def run(vendor, scenario, rates=None):
    rates = RATES if rates is None else rates
    service, port = SERVICES[vendor]
    endpoint = f'http://localhost:{port}' + ('/benchmark.fluentd' if vendor == 'fluentd' else '')
    root = Path('benchmark_results'); root.mkdir(exist_ok=True)
    # Corpus is immutable, identical on all instances, and retained with results.
    payload = Path('fixed-nginx.ndjson')
    base = ['loadgen-rust', '--dispatch-mode', 'workers', '--endpoint', endpoint, '--number', '1', '--workers', '256', '--timeout', '30s', '--max-retries', '2', '--retry-ambiguous', '--fixed-payload-file', str(payload)]
    payload_sha = hashlib.sha256(payload.read_bytes()).hexdigest()
    # Calibrate all rates once per instance, including rates later skipped for an agent.
    for rate in rates:
        cal = root / f'{vendor}_{rate}.calibration.json'
        if not cal.exists():
            subprocess.run(['sudo', 'systemctl', 'stop', service], check=True)
            subprocess.run([*base, '--fixed-rate', str(rate), '--fixed-calibration', '--fixed-warmup', '2s', '--total-time', '10s', '--fixed-output', str(cal)], check=True)
    shortfall = None
    for rate in rates:
        path = root / f'{vendor}_{scenario}_{rate}.fixed.json'
        if shortfall is not None:
            path.write_text(json.dumps({'schema_version': 2, 'vendor': vendor, 'scenario': scenario,
                'target_logs_per_second': rate, 'complete': True, 'status': 'skipped_after_shortfall',
                'payload_sha256': payload_sha, 'trigger_target_logs_per_second': shortfall}, indent=2) + '\n')
            print(f'{vendor}/{scenario}/{rate}: not tested after {shortfall} target shortfall', flush=True)
            continue
        print(f'{vendor}/{scenario}/{rate}: starting independent fixed-rate measurement', flush=True)
        record = {'schema_version': 2, 'vendor': vendor, 'scenario': scenario, 'target_logs_per_second': rate, 'complete': False}
        path.write_text(json.dumps(record) + '\n')
        try:
            subprocess.run(['sudo', 'systemctl', 'start', service], check=True)
            invocation = ready(service, port)
            cgroup = systemctl('show', service, '-p', 'ControlGroup', '--value')
            if not cgroup: raise RuntimeError('Service has no cgroup')
            own = next((line.split(':',2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')), '')
            if not own: raise RuntimeError('Generator cgroup v2 is unavailable')
            if own == cgroup or own.startswith(cgroup.rstrip('/')+'/'): raise RuntimeError('Generator shares measured agent cgroup')
            record['generator_limits'] = collect_machine.limits(own)
            own_status = collect_machine.read('/proc/self/status') or ''
            record['generator_limits']['main_process_cpu_affinity'] = next((line.split(':',1)[1].strip() for line in own_status.splitlines() if line.startswith('Cpus_allowed_list:')), None)
            record['limits'] = collect_machine.limits(cgroup)
            main_pid = systemctl('show', service, '-p', 'MainPID', '--value')
            status = collect_machine.read('/proc/' + main_pid + '/status') or ''
            record['limits']['main_process_cpu_affinity'] = next((line.split(':',1)[1].strip() for line in status.splitlines() if line.startswith('Cpus_allowed_list:')), None)
            raw = path.with_suffix('.loadgen.json')
            subprocess.run([*base, '--fixed-rate', str(rate), '--fixed-warmup', '10s', '--total-time', '60s', '--fixed-cgroup', '/sys/fs/cgroup' + cgroup, '--fixed-output', str(raw)], check=True)
            record['loadgen'] = json.loads(raw.read_text())
            raw.unlink()  # Complete raw loadgen record is embedded in the retained tier JSON.
            record['service_unchanged'] = invocation == systemctl('show', service, '-p', 'InvocationID', '--value') and systemctl('show', service, '-p', 'ActiveState', '--value') == 'active'
            drain_start = time.monotonic()
            time.sleep(60)
            record['agent_drain_observation_seconds'] = time.monotonic() - drain_start
            record['agent_backlog_before'] = None; record['agent_backlog_after'] = None
            record['service_unchanged'] = record['service_unchanged'] and invocation == systemctl('show', service, '-p', 'InvocationID', '--value') and systemctl('show', service, '-p', 'ActiveState', '--value') == 'active'
            record['complete'] = True
        finally:
            stopped = subprocess.run(['sudo', 'systemctl', 'stop', service], check=False).returncode == 0
            if not stopped: record['complete'] = False
            path.write_text(json.dumps(record, indent=2) + '\n')
            if not stopped: raise RuntimeError('Service did not stop between tiers')
        if not record.get('service_unchanged'): raise RuntimeError('Service stopped or restarted during fixed-rate tier')
        outcome = fixed.tier(root, vendor, scenario, rate, payload_sha)
        print(f'{vendor}/{scenario}/{rate}: {outcome["status"]}: {outcome["reason"]}', flush=True)
        if outcome['status'] not in fixed.MEASURED_STATUSES:
            raise RuntimeError(f'Invalid measurement: {outcome["reason"]}')
        if outcome['status'] in fixed.SHORTFALL_STATUSES:
            shortfall = rate


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('vendor', choices=SERVICES); p.add_argument('scenario'); a = p.parse_args(); run(a.vendor, a.scenario)
