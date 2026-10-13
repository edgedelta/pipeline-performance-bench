#!/usr/bin/env python3
"""Fetch the stable RED Linux release and verify its published SHA-256."""
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

if __name__ == '__main__':
    print(json.dumps(fetch(sys.argv[1], os.environ.get('RED_VERSION'))))
