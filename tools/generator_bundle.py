#!/usr/bin/env python3
"""Bind both Linux executables to the checked-out sources before provisioning."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(root):
    paths = [root / p for p in ('tools/build_generators.sh', 'tools/build_loadgen.sh',
             'tools/generator_bundle.py', 'patches/loadgen-retry.patch',
             'payloads/fixed-nginx.ndjson', 'loadgen-rust/Cargo.toml', 'loadgen-rust/Cargo.lock')]
    paths += sorted((root / 'loadgen-rust/src').rglob('*.rs'))
    paths += sorted((root / 'loadgen_extensions').glob('*.go'))
    return {str(p.relative_to(root)): sha(p) for p in paths}


def verify(directory, root=ROOT):
    manifest = json.loads((directory / 'generators.json').read_text())
    if manifest['sources'] != sources(root):
        raise ValueError('Generator bundle does not match the checked-out sources')
    for name in ('loadgen', 'loadgen-rust'):
        binary = directory / name
        # ELF64, little-endian, Linux x86_64 machine code (not a macOS/ARM build).
        header = binary.read_bytes()[:20]
        if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
            raise ValueError(f'{name}: expected Linux x86_64 ELF')
        if sha(binary) != manifest['binaries'][name]:
            raise ValueError(f'{name}: checksum mismatch')
        binary.chmod(0o755)  # GitHub artifact transport removes executable bits.
    for name, binary in [('provenance.json', 'loadgen'), ('rust-provenance.json', 'loadgen-rust')]:
        if sha(directory / name) != manifest['metadata'][name]:
            raise ValueError(f'{name}: checksum mismatch')
        if json.loads((directory / name).read_text())['binary_sha256'] != manifest['binaries'][binary]:
            raise ValueError(f'{name}: binary provenance mismatch')
    return manifest


def create(directory):
    rust = {'generator': 'rust', 'dispatch_mode': 'workers', 'workers': 256,
            'target': 'x86_64-unknown-linux-gnu', 'build_os': 'Ubuntu 24.04',
            'compiler': subprocess.check_output(['rustc', '+1.98.0', '--version'], text=True).strip(),
            'version': subprocess.check_output([str(directory.resolve() / 'loadgen-rust'), '--version'], text=True).strip(),
            'binary_sha256': sha(directory / 'loadgen-rust'),
            'source_sha256': sources(ROOT)}
    (directory / 'rust-provenance.json').write_text(json.dumps(rust, indent=2) + '\n')
    manifest = {'sources': sources(ROOT),
                'binaries': {name: sha(directory / name) for name in ('loadgen', 'loadgen-rust')},
                'metadata': {name: sha(directory / name) for name in ('provenance.json', 'rust-provenance.json')}}
    (directory / 'generators.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify(directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    (create if args.action == 'create' else verify)(args.directory)
