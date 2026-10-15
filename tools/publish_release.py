#!/usr/bin/env python3
"""Publish validated benchmark evidence, including labeled target shortfalls, as an immutable dated release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from check_results import validate
from report_disclosure import disclosure


def release_notes(report, run_url, data=None):
    """Use the concise summary in both preview and release; retain the full report asset."""
    synthetic = (data or {}).get('synthetic') or 'SYNTHETIC FIXTURE' in report
    if data and {'hardware', 'fixed_throughput', 'versions', 'scenarios', 'runId'} <= data.keys():
        from release_report import render
        return render(data, run_url, synthetic)
    if (data or {}).get('fixed_throughput', {}).get('measured'):
        tiers = [t for t in data['fixed_throughput']['tiers'].values() if t['status'] != 'unsupported']
        sustained = sum(t['status'] == 'ok' for t in tiers)
        failed = sum(t['status'] in ('capacity_limited', 'generator_limited') for t in tiers)
        skipped = sum(t['status'] == 'skipped_after_shortfall' for t in tiers)
        uncertain = sum(t['status'] == 'generator_limited' for t in tiers)
        intro = (f"Supported best-throughput scenarios; **{sustained} fixed-rate targets passed, "
                 f"{failed} failed to sustain target, {skipped} higher tiers not tested**. "
                 "Failed attainment is a benchmark outcome, not a successful target test. "
                 f"**{uncertain} measured tiers have generator/bottleneck uncertainty** and do not establish agent-only capacity. "
                 "Only sustained, comparable tiers qualify for resource comparisons. "
                 "Agents use separate instances, with sequential scenarios and tiers.\n\n")
    else:
        intro = 'Best-tested-throughput results; fixed-rate resource comparisons were not measured in this result format.\n\n'
    scenarios = (data or {}).get('scenarios', {})
    measured_errors = [entry for entry in scenarios.values() if entry['status'] == 'errors']
    if measured_errors:
        errors = sum(tier.get('errors') or 0 for entry in measured_errors for tier in entry.get('workers', []))
        intro += (f'**Best-throughput reliability: {len(measured_errors)} scenario(s) recorded '
                  f'{errors:,} unrecovered request errors across their worker tiers.** '
                  'These scenarios remain labeled `errors` and are excluded from throughput rankings and cross-scenario comparisons.\n\n')
    intro = disclosure((data or {}).get('provenance')) + intro
    if synthetic: intro = '> **SYNTHETIC FIXTURE PREVIEW — NOT REAL RESULTS. DO NOT PUBLISH.**\n\n' + intro
    return intro + f'[Workflow run]({run_url})\n\n' + report


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def publish(directory, repo, commit, run_url):
    directory = Path(directory)
    provenance = json.loads((directory / 'provenance.json').read_text()) if (directory / 'provenance.json').exists() else {}
    if provenance.get('benchmark_profile') == 'short':
        raise ValueError('Short validation runs cannot be published as benchmark releases')
    if not (directory / 'SHA256SUMS').exists():
        print('Partial suite: results uploaded as workflow artifacts; no release published.')
        return
    data = validate(directory)
    # validate() rejects incomplete/invalid evidence. Measured request errors and
    # target shortfalls are reportable outcomes, not publication failures.
    if data['provenance']['benchmark_commit'] != commit:
        raise ValueError('Release commit must match measured source')
    if not re.fullmatch(r'\d{8}_\d{6}', directory.name):
        raise ValueError('Expected UTC run timestamp YYYYMMDD_HHMMSS')
    tag = directory.name.replace('_', '-')
    title = f'Benchmark Report - {tag}'
    releases = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases'))
    existing = next((r for page in releases for r in page if r['tag_name'] == tag), None)
    if existing and not existing['draft']:
        print(f'Release already published: {existing["html_url"]}')
        return
    with tempfile.TemporaryDirectory() as temp:
        notes = Path(temp) / 'notes.md'
        notes.write_text(release_notes((directory / 'report.md').read_text(), run_url, data))
        if not existing:
            gh('release', 'create', tag, '--repo', repo, '--target', commit,
               '--title', title, '--notes-file', str(notes), '--draft')
        else:
            gh('release', 'edit', tag, '--repo', repo, '--title', title, '--notes-file', str(notes))
        assets = [directory / line.split('  ', 1)[1] for line in (directory / 'SHA256SUMS').read_text().splitlines()]
        assets.append(directory / 'SHA256SUMS')
        for offset in range(0, len(assets), 20):
            gh('release', 'upload', tag, '--repo', repo, '--clobber', *(str(p) for p in assets[offset:offset+20]))
        pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases'))
        release = next(r for page in pages for r in page if r['tag_name'] == tag)
        asset_pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases/{release["id"]}/assets?per_page=100'))
        remote = {a['name']: a.get('digest') for page in asset_pages for a in page}
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
