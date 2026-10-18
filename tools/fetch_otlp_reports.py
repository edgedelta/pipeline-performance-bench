"""Fetch the newest complete published OTLP pair for the static site."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def fetch(repo, output):
    releases = json.loads(subprocess.check_output(['gh', 'release', 'list', '--repo', repo, '--limit', '1000', '--exclude-drafts', '--json', 'tagName'], text=True))
    tag = next((r['tagName'] for r in releases if r['tagName'].startswith('otlp-') and not r['tagName'].startswith('otlp-pr')), None)
    if tag is None:
        print('No daily OTLP release yet; using saved datasets')
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        subprocess.run(['gh', 'release', 'download', tag, '--repo', repo, '--dir', str(tmp), '--pattern', 'metrics.json', '--pattern', 'traces.json', '--pattern', 'SHA256SUMS'], check=True)
        hashes = dict(line.split('  ', 1)[::-1] for line in (tmp / 'SHA256SUMS').read_text().splitlines())
        for signal in ['metrics', 'traces']:
            file = tmp / f'{signal}.json'
            if hashlib.sha256(file.read_bytes()).hexdigest() != hashes[file.name]:
                raise ValueError('OTLP release data checksum mismatch')
            data = json.loads(file.read_text())
            if data.get('signal') != signal or data.get('profile') != 'full':
                raise ValueError('OTLP release signal/profile mismatch')
        output.mkdir(parents=True, exist_ok=True)
        for signal in ['metrics', 'traces']:
            (output / f'{signal}.json').write_bytes((tmp / f'{signal}.json').read_bytes())
    print('Using OTLP release ' + tag)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('repo')
    p.add_argument('output', type=Path)
    a = p.parse_args()
    fetch(a.repo, a.output)
