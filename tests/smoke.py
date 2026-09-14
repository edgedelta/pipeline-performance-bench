#!/usr/bin/env python3
"""Validate production configs, then test the same HTTP sources/transforms with stdout sinks.
Requires Docker and PyYAML. Does not contact AWS or cloud control planes.
"""
import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGES = {'vector': 'timberio/vector:latest-debian', 'fluentbit': 'fluent/fluent-bit:latest'}
EVENTS = [
    {'id': 'keep', 'pii': {'color': 'Blue', 'ipv4': '54.53.50.1', 'email': 'alice@example.com', 'mastercard': '5555555555554444', 'amex': '378282246310005', 'visa': '4111111111111111', 'discover': '6011111111111117', 'iban': 'GB82WEST12345698765432', 'ipv6': '2001:db8:85a3:0000:0000:8a2e:0370:7334', 'mac': '00:11:22:33:44:55'}},
    {'id': 'drop', 'pii': {'color': 'Green', 'ipv4': '192.0.2.42'}},
    {'id': 'missing'},
]

def docker(*args, check=True):
    return subprocess.run(['docker', *args], check=check, text=True, capture_output=True)


def run_case(vendor, case, directory):
    extension = 'yaml' if vendor == 'vector' else 'conf'
    source = ROOT / 'pipelines' / vendor / f'{case}.{extension}'
    production = directory / f'{vendor}-{case}-production.{extension}'
    production.write_text(source.read_text().replace('{S3_PLACEHOLDER}', 'pipeline-bench-validation'))
    common = ['--rm', '-v', f'{directory}:/test:ro', '-v', f'{ROOT}/pipelines/lookup-benchmark.csv:/tmp/lookup-benchmark.csv:ro', '-v', f'{ROOT}/pipelines/fluentbit/lookup.lua:/etc/fluent-bit/lookup.lua:ro', '-e', 'AWS_ACCESS_KEY_ID=validation', '-e', 'AWS_SECRET_ACCESS_KEY=validation', '-e', 'AWS_EC2_METADATA_DISABLED=true']
    validate = ['validate', '--skip-healthchecks', f'/test/{production.name}'] if vendor == 'vector' else ['--dry-run', '-c', f'/test/{production.name}']
    result = docker('run', *common, '--network', 'none', IMAGES[vendor], *validate, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    if vendor == 'vector':
        config = yaml.safe_load(production.read_text())
        config['sinks'] = {'console': {'type': 'console', 'inputs': config['sinks']['s3']['inputs'], 'encoding': {'codec': 'json'}}}
        contents = yaml.safe_dump(config)
        port = 4085
    else:
        contents = production.read_text().split('[OUTPUT]')[0] + '[OUTPUT]\n    Name stdout\n    Match *\n    Format json_lines\n'
        port = 2085
    smoke = directory / f'{vendor}-{case}.{extension}'
    smoke.write_text(contents)
    args = ['--config', f'/test/{smoke.name}'] if vendor == 'vector' else ['-c', f'/test/{smoke.name}']
    cid = docker('run', '-d', *common, '-p', f'127.0.0.1::{port}', IMAGES[vendor], *args).stdout.strip()
    try:
        mapped = docker('port', cid, f'{port}/tcp').stdout.strip()
        endpoint = f'http://{mapped}/'
        # A GET establishes readiness without injecting test events.
        for _ in range(100):
            try:
                urllib.request.urlopen(endpoint, timeout=1).close()
                break
            except urllib.error.HTTPError:
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.1)
        else:
            raise AssertionError('HTTP source did not start: ' + docker('logs', cid).stderr)
        for event in EVENTS:
            request = urllib.request.Request(endpoint, json.dumps(event).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert 200 <= response.status < 300
        records = []
        expected = 2 if case == 'filter' else 3
        for _ in range(50):
            records = []
            for line in docker('logs', cid).stdout.splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict) and event.get('id'):
                        records.append(event)
                except json.JSONDecodeError:
                    pass
            if len(records) >= expected:
                break
            time.sleep(.1)
        assert len(records) == expected, (vendor, case, records)
        got = {event['id']: event for event in records}
        if case == 'filter':
            assert set(got) == {'keep', 'missing'}, got
        elif case == 'lookup':
            assert (got['keep']['region'], got['keep']['env']) == ('ap-northeast', 'dev'), got
            for key in ['drop', 'missing']:
                assert (got[key]['region'], got[key]['env']) == ('Unknown', 'Unknown'), got
        elif case == 'mask':
            for field in EVENTS[0]['pii']:
                if field != 'color':
                    assert got['keep']['pii'][field] == 'REDACTED', (field, got['keep'])
            assert got['keep']['pii']['color'] == 'Blue'
        else:
            assert got['keep']['pii'] == EVENTS[0]['pii'], got
        print(f'PASS {vendor}/{case}: production config + HTTP behavior', flush=True)
    finally:
        docker('stop', '-t', '2', cid, check=False)

if __name__ == '__main__':
    for image in IMAGES.values():
        docker('pull', image)
    with tempfile.TemporaryDirectory(prefix='pipeline-bench-smoke-') as tmp:
        directory = pathlib.Path(tmp)
        for vendor, cases in [('vector', ['pass-through', 'filter', 'mask', 'lookup']), ('fluentbit', ['pass-through', 'filter', 'lookup'])]:
            for case in cases:
                run_case(vendor, case, directory)
