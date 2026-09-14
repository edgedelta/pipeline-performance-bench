#!/usr/bin/env python3
"""Publish a complete, successful benchmark as an immutable dated release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from check_results import validate


def release_notes(report, run_url):
    """Keep release presentation focused on measured performance."""
    report = re.sub(r'^- Reliability tables.*\n', '', report, flags=re.M)
    report = re.sub(r'^\*\*Delivery policy:\*\*.*\n\n', '', report, flags=re.M)
    report = re.sub(r'### Reliability Comparison\n.*?(?=^## |\Z)', '', report, flags=re.S | re.M)
    report = re.sub(r'loadgen [^,]+,', 'loadgen (exact build recorded in provenance),', report)
    report = re.sub(r'^\*\*Rust source:\*\* `None`\n', '', report, flags=re.M)
    return ('All **26 supported scenarios / 78 worker tiers** completed successfully. '
            'Seven agents ran in parallel on separate identical EC2 instances. '
            'Agent versions were resolved from their current installation channels for this run.\n\n'
            f'[Workflow run]({run_url})\n\n' + report)


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def publish(directory, repo, commit, run_url):
    directory = Path(directory)
    if not (directory / 'SHA256SUMS').exists():
        print('Partial suite: results uploaded as workflow artifacts; no release published.')
        return
    data = validate(directory)
    if any(entry['status'] not in ('ok', 'unsupported') for entry in data['scenarios'].values()):
        raise ValueError('Only a complete successful suite may be published')
    if data['provenance']['benchmark_commit'] != commit:
        raise ValueError('Release commit must match measured source')
    if not re.fullmatch(r'\d{8}_\d{6}', directory.name):
        raise ValueError('Expected UTC run timestamp YYYYMMDD_HHMMSS')
    tag = directory.name.replace('_', '-')
    title = f'Pipeline performance benchmark — {tag[:4]}-{tag[4:6]}-{tag[6:8]} {tag[9:11]}:{tag[11:13]} UTC'
    releases = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases'))
    existing = next((r for page in releases for r in page if r['tag_name'] == tag), None)
    if existing and not existing['draft']:
        print(f'Release already published: {existing["html_url"]}')
        return
    with tempfile.TemporaryDirectory() as temp:
        notes = Path(temp) / 'notes.md'
        notes.write_text(release_notes((directory / 'report.md').read_text(), run_url))
        if not existing:
            gh('release', 'create', tag, '--repo', repo, '--target', commit,
               '--title', title, '--notes-file', str(notes), '--draft')
        else:
            gh('release', 'edit', tag, '--repo', repo, '--title', title, '--notes-file', str(notes))
        assets = [directory / line.split('  ', 1)[1] for line in (directory / 'SHA256SUMS').read_text().splitlines()]
        assets.append(directory / 'SHA256SUMS')
        gh('release', 'upload', tag, '--repo', repo, '--clobber', *(str(p) for p in assets))
        pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases'))
        release = next(r for page in pages for r in page if r['tag_name'] == tag)
        remote = {a['name']: a.get('digest') for a in release['assets']}
        expected = {p.name: 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}
        if remote != expected:
            raise ValueError('Uploaded assets differ from validated local assets; leaving draft unpublished')
        gh('api', '--method', 'PATCH', f'repos/{repo}/releases/{release["id"]}',
           '-F', 'draft=false', '-f', 'make_latest=true')
        print(release['html_url'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--run-url', required=True)
    args = parser.parse_args()
    publish(args.directory, args.repo, args.commit, args.run_url)
