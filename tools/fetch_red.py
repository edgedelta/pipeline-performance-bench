#!/usr/bin/env python3
"""Fetch the stable RED Linux release and verify its published SHA-256."""
import argparse
import time
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import zipfile

BASE = 'https://release.edgedelta.com/red'
REPO = 'edgedelta/red'
STABLE = re.compile(r'\d+\.\d+\.\d+')

def download(url, output=None):
    # curl uses the host trust store, including macOS enterprise certificates.
    command = ['curl', '--fail', '--silent', '--show-error', '--location',
               '--retry', '3', '--connect-timeout', '15', '--max-time', '120', url]
    if output is not None:
        subprocess.run(command + ['--output', str(output)], check=True)
        return None
    return subprocess.check_output(command)


def latest_tag():
    # The latest GitHub release excludes drafts and prereleases (RC tags).
    tag = subprocess.check_output(['gh', 'api', f'repos/{REPO}/releases/latest',
                                   '--jq', '.tag_name']).decode().strip()
    return tag.removeprefix('v')


def stable_version():
    # release.edgedelta.com answers missing paths with an HTML index page, so a
    # vanished stable-version pointer is only detectable by its content.
    pointer = download(BASE + '/stable-version').decode().strip()
    if STABLE.fullmatch(pointer):
        return pointer
    if not os.environ.get('GH_TOKEN'):
        raise ValueError(f'{BASE}/stable-version did not return X.Y.Z; set RED_VERSION '
                         f'or GH_TOKEN with read access to {REPO} releases')
    return latest_tag()


def fetch(directory, version=None):
    directory = Path(directory)
    version = version or stable_version()
    if not STABLE.fullmatch(version):
        raise ValueError('RED_VERSION must be a stable X.Y.Z release')
    name = f'red-{version}-x86_64-unknown-linux-gnu.zip'
    url = f'{BASE}/{version}/{name}'
    expected = download(url + '.sha256').decode().split()[0]
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
        raise ValueError('Invalid RED package checksum')
    directory.mkdir(parents=True, exist_ok=True)
    package = directory / 'red.zip'
    download(url, package)
    actual = hashlib.sha256(package.read_bytes()).hexdigest()
    if actual != expected.lower():
        package.unlink()
        raise ValueError('RED package checksum mismatch')
    with zipfile.ZipFile(package) as archive:
        binary = archive.read('red')
    (directory / 'red').write_bytes(binary)
    (directory / 'red').chmod(0o755)
    metadata = {'version': version, 'url': url, 'package_sha256': actual,
                'binary_sha256': hashlib.sha256(binary).hexdigest(), 'channel': 'stable'}
    (directory / 'release.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata

def fetch_candidate(directory, required_commit=None):
    releases = json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/releases?per_page=100'], text=True))
    release = next((r for r in releases if not r['draft'] and r['prerelease'] and re.fullmatch(r'v\d+\.\d+\.\d+-rc\.\d+', r['tag_name']) and (not required_commit or r['target_commitish'] == required_commit)), None)
    if release is None:
        raise LookupError('No qualified candidate published for the requested Rust commit')
    candidate = release['tag_name'].removeprefix('v')
    base = f'{BASE}/candidates/{candidate}'
    manifest = json.loads(download(base + '/release-manifest.json'))
    if (required_commit and manifest['commit'] != required_commit) or manifest['qualification'] != 'PASS' or manifest['candidate_version'] != candidate or not re.fullmatch(r'[a-f0-9]{40}', manifest['commit']):
        raise ValueError('Candidate provenance is invalid')
    name = f"red-{manifest['version']}-x86_64-unknown-linux-gnu.zip"
    expected = download(f'{base}/{name}.sha256').decode().split()[0]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    package = directory / 'red.zip'
    download(f'{base}/{name}', package)
    actual = hashlib.sha256(package.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError('Candidate package checksum mismatch')
    with zipfile.ZipFile(package) as archive:
        packaged = json.loads(archive.read('manifest.json'))
        binary = archive.read('red')
        if packaged['commit'] != manifest['commit'] or packaged['profile'] != 'release' or packaged['target'] != 'x86_64-unknown-linux-gnu' or packaged['worktree_dirty']:
            raise ValueError('Candidate package source/build mismatch')
        if hashlib.sha256(binary).hexdigest() != packaged['sha256']:
            raise ValueError('Candidate binary checksum mismatch')
    (directory / 'red').write_bytes(binary)
    (directory / 'red').chmod(0o755)
    metadata = {'version': candidate, 'source_commit': manifest['commit'], 'url': f'{base}/{name}',
                'package_sha256': actual, 'binary_sha256': hashlib.sha256(binary).hexdigest(), 'channel': 'candidate'}
    (directory / 'release.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (directory / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--candidate', action='store_true')
    parser.add_argument('--commit')
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args()
    if args.commit and not re.fullmatch(r'[a-f0-9]{40}', args.commit):
        parser.error('--commit must be a full source SHA')
    deadline = time.monotonic() + args.wait_seconds
    while True:
        try:
            result = fetch_candidate(args.directory, args.commit) if args.candidate else fetch(args.directory, os.environ.get('RED_VERSION'))
            print(json.dumps(result), flush=True)
            break
        except LookupError:
            if time.monotonic() >= deadline:
                raise
            print('Waiting for the requested Rust candidate to finish qualification...', flush=True)
            time.sleep(30)
