#!/usr/bin/env python3
"""Create and remove a unique, self-managed Cribl Edge fleet for one shard."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import uuid


def request(url, method='GET', token=None, body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            content = response.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as error:
        if error.code != 404:
            detail = error.read().decode(errors='replace')
            for value in [token, *(v for k, v in os.environ.items() if k.startswith('CRIBL_'))]:
                if value:
                    detail = detail.replace(value, '[redacted]')
            print(f'Cribl {method} HTTP {error.code}: {detail[:2000]}', file=sys.stderr)
        raise


def credentials():
    token = request('https://login.cribl.cloud/oauth/token', 'POST', body={
        'grant_type': 'client_credentials', 'client_id': os.environ['CRIBL_CLIENT_ID'],
        'client_secret': os.environ['CRIBL_CLIENT_SECRET'], 'audience': 'https://api.cribl.cloud'})['access_token']
    base = f'https://{os.environ["CRIBL_WORKSPACE"]}-{os.environ["CRIBL_ORG"]}.cribl.cloud/api/v1/products/edge/groups'
    return base, token


def create(state):
    if state.exists():
        raise ValueError('Fleet state exists; clean it up before creating another fleet')
    base, token = credentials()
    fleet = 'pipeline-perf-' + uuid.uuid4().hex
    # Persist ownership before POST, including when a response is lost.
    state.write_text(json.dumps({'id': fleet, 'base': base}) + '\n')
    state.chmod(0o600)
    request(base, 'POST', token, {'id': fleet, 'name': fleet,
            'description': 'Temporary pipeline benchmark scenario fleet',
            'isFleet': True, 'isSearch': False, 'onPrem': True, 'workerRemoteAccess': True})
    return fleet


def delete(state):
    if not state.exists():
        return
    saved = json.loads(state.read_text())
    base, token = credentials()
    if saved['base'] != base or not re.fullmatch(r'pipeline-perf-[a-f0-9]{32}', saved['id']):
        raise ValueError('Refusing to delete a fleet outside this benchmark state')
    url = base + '/' + saved['id']
    try:
        request(url, 'DELETE', token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    try:
        result = request(url, token=token)
        if result.get('items'):
            raise ValueError('Fleet still exists after deletion')
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    state.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['create', 'delete'])
    parser.add_argument('state', type=Path)
    args = parser.parse_args()
    if args.command == 'create':
        print(create(args.state))
    else:
        delete(args.state)
