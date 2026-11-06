"""Readiness probes and the bounded retry policy for the request-rate ladders.

Standard library only, so the unit tests run without the OTLP protobuf packages.
"""
import json
from pathlib import Path


# Runs on a remote host: report when host:port has accepted TCP connections for
# `stable` consecutive one-second probes, or give up after `timeout` seconds.
PROBE = '''import json,socket,sys,time
host,port,stable,timeout=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),float(sys.argv[4])
start=time.monotonic();run=successes=failures=0;ready=False
while time.monotonic()-start<timeout:
    try:
        with socket.create_connection((host,port),timeout=2): ok=True
    except OSError: ok=False
    if ok: successes+=1;run+=1
    else: failures+=1;run=0
    if run>=stable: ready=True;break
    time.sleep(1)
print(json.dumps(dict(ready=ready,successes=successes,failures=failures,seconds=round(time.monotonic()-start,2))))'''


def wait_reachable(host, address, port, stable=3, timeout=60):
    """Probe address:port from `host` (the load generator) until it is stably reachable."""
    return json.loads(host.argv(['python3', '-c', PROBE, address, str(port), str(stable), str(timeout)]))


# Statuses caused by the harness or hosts rather than by the agent under test.
INFRA_FAILURES = {'execution_failed', 'agent_unreachable'}
MAX_ATTEMPTS = 2


def should_retry(status, attempt, attempts=MAX_ATTEMPTS):
    """Retry a measurement once when it failed for an infrastructure reason; never retry a result."""
    return status in INFRA_FAILURES and attempt + 1 < attempts


def run_attempts(measure, prefix, report, save):
    """Run one measurement, retrying once on an infrastructure failure, and record every attempt."""
    prefix = Path(prefix)
    for attempt in range(MAX_ATTEMPTS):
        row = measure()
        if should_retry(row['status'], attempt):
            # Keep the failed attempt's evidence under an attempt-numbered name; the retry starts a fresh agent process.
            for suffix in ['agent.log', 'warmup.json']:
                evidence = prefix.with_name(f'{prefix.name}-{suffix}')
                if evidence.exists(): evidence.rename(prefix.with_name(f'{prefix.name}-attempt{attempt}-{suffix}'))
            report.setdefault('retried', []).append(dict(row, attempt=attempt)); save()
            print(json.dumps({'vendor': row.get('vendor'), 'batch': row.get('batch'), 'rps': row.get('target_rps'), 'status': row['status'], 'attempt': attempt, 'retrying': True}), flush=True)
            continue
        row['attempts'] = attempt + 1
        report['rows'].append(row); save()
        print(json.dumps({'vendor': row.get('vendor'), 'batch': row.get('batch'), 'rps': row.get('target_rps'), 'achieved': row.get('load', {}).get('achieved_rps'),
                          'cpu': row.get('through_delivery', {}).get('cpu_cores'), 'status': row['status'], 'attempts': row['attempts']}), flush=True)
        return row
