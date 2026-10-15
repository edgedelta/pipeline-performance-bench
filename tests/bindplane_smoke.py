#!/usr/bin/env python3
"""Check Bindplane production configs and HTTP behavior with an unpacked official collector.

Usage: python3 tests/bindplane_smoke.py /path/to/observiq-otel-collector
Requires PyYAML. Uses local fixtures and a file sink; no AWS resources are created.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import yaml
from smoke import EVENTS

ROOT = Path(__file__).resolve().parents[1]


def decode(value):
    if 'kvlistValue' in value:
        return {v['key']: decode(v['value']) for v in value['kvlistValue']['values']}
    return value.get('stringValue')


def run(binary, case, production):
    with tempfile.TemporaryDirectory(prefix='bindplane-smoke-') as tmp:
        directory = Path(tmp)
        config = yaml.safe_load((ROOT / f'pipelines/bindplane/{case}.yaml').read_text().replace('{S3_PLACEHOLDER}', 'pipeline-bench-validation'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        config['receivers']['webhook_event']['endpoint'] = f'127.0.0.1:{port}'
        if case == 'lookup':
            config['processors']['lookup']['csv'] = str(ROOT / 'pipelines/lookup-benchmark.csv')
        if not production:
            config['exporters'] = {'file': {'path': str(directory / 'out.json')}}
            config['processors']['batch']['timeout'] = '100ms'
            config['service']['pipelines']['logs']['exporters'] = ['file']
        (directory / 'config.yaml').write_text(yaml.safe_dump(config))
        env = dict(os.environ, AWS_ACCESS_KEY_ID='validation', AWS_SECRET_ACCESS_KEY='validation', AWS_EC2_METADATA_DISABLED='true')
        endpoint = f'http://127.0.0.1:{port}/'
        with (directory / 'log').open('w') as log:
            process = subprocess.Popen([str(binary), '--config', str(directory / 'config.yaml'), '--logging', str(binary.parent / 'logging.yaml')], cwd=directory, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise AssertionError((directory / 'log').read_text())
                    try:
                        with urllib.request.urlopen(endpoint, timeout=.1):
                            pass
                        break
                    except urllib.error.HTTPError:
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError('HTTP receiver did not start: ' + (directory / 'log').read_text())
                if not production:
                    for event in EVENTS:
                        request = urllib.request.Request(endpoint, json.dumps(event).encode(), {'Content-Type': 'application/json'})
                        with urllib.request.urlopen(request, timeout=5) as response:
                            if not 200 <= response.status < 300:
                                raise AssertionError(response.status)
                    time.sleep(.5)
            finally:
                process.terminate()
                process.wait(timeout=10)
        if production:
            return
        records = []
        for line in (directory / 'out.json').read_text().splitlines():
            for resource in json.loads(line)['resourceLogs']:
                for scope in resource['scopeLogs']:
                    for record in scope['logRecords']:
                        body = decode(record['body'])
                        records.append(json.loads(body) if isinstance(body, str) else body)
        expected = {'keep', 'missing'} if case == 'filter' else {'keep', 'drop', 'missing'}
        got = {record['id']: record for record in records}
        if set(got) != expected or len(records) != len(expected):
            raise AssertionError((case, records))
        if case == 'lookup':
            for key in expected:
                wanted = ('ap-northeast', 'dev') if key == 'keep' else ('Unknown', 'Unknown')
                if (got[key]['region'], got[key]['env']) != wanted:
                    raise AssertionError((case, key, got[key]))
        elif case == 'mask':
            for field, value in EVENTS[0]['pii'].items():
                actual = got['keep']['pii'][field]
                if (field == 'color' and actual != value) or (field != 'color' and (actual == value or '*' not in actual)):
                    raise AssertionError((case, field, actual))
        elif got['keep'] != EVENTS[0]:
            raise AssertionError((case, got['keep']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    for case in ['pass-through', 'filter', 'mask', 'lookup']:
        for production in [True, False]:
            run(args.binary.resolve(), case, production)
        print(f'PASS bindplane/{case}: production config + HTTP behavior', flush=True)
