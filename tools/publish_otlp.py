"""Publish a complete daily OTLP pair and its raw evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def package(root, output, commit):
    output.mkdir(parents=True, exist_ok=True)
    rust_hashes = set()
    for signal in ['metrics', 'traces']:
        matches = list(root.glob(f'*/{signal}.json'))
        if len(matches) != 1:
            raise ValueError(f'{signal}: expected exactly one result')
        data = json.loads(matches[0].read_text())
        if data.get('profile') != 'full' or data.get('benchmark_commit') != commit:
            raise ValueError('Only complete full runs from the measured commit can be published')
        if len(data['rows']) != 60 or any(r['status'] not in ('measured', 'input_shortfall') for r in data['rows']):
            raise ValueError('Incomplete or invalid OTLP report')
        rust_hashes.add(data['binary_sha256'])
        (output / f'{signal}.json').write_bytes(matches[0].read_bytes())
    if len(rust_hashes) != 1:
        raise ValueError('Signals used different Rust binaries')
    with tarfile.open(output / 'otlp-evidence.tar.gz', 'w:gz') as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(root)))
    assets = sorted(output.iterdir())
    (output / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in assets))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--commit', required=True)
    p.add_argument('--tag', required=True)
    p.add_argument('--repo', required=True)
    p.add_argument('--publish', action='store_true')
    a = p.parse_args()
    package(a.root, a.output, a.commit)
    if not a.publish:
        return
    notes = a.output / 'NOTES.md'
    notes.write_text('Daily metrics and trace ladders. Both signals use isolated agent/load/sink hosts and the same verified Rust candidate. Measured load shortfalls remain in the data. The archive includes all configs, raw results and agent logs.\n')
    gh('release', 'create', a.tag, '--repo', a.repo, '--target', a.commit, '--draft', '--title', f'OTLP Benchmark Report - {a.tag}', '--notes-file', str(notes))
    assets = [p for p in a.output.iterdir() if p.name != 'NOTES.md']
    gh('release', 'upload', a.tag, '--repo', a.repo, *(str(p) for p in assets))
    release = json.loads(gh('api', f'repos/{a.repo}/releases/tags/{a.tag}'))
    expected = {p.name: 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}
    if {asset['name']: asset.get('digest') for asset in release['assets']} != expected:
        raise ValueError('Uploaded evidence checksum mismatch; draft retained')
    gh('release', 'edit', a.tag, '--repo', a.repo, '--draft=false', '--latest=false')


if __name__ == '__main__':
    main()
