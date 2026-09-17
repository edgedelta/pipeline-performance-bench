"""Describe AI involvement without claiming an LLM generates measurements."""
import re


def disclosure(provenance=None):
    commit = (provenance or {}).get('benchmark_commit', '')
    ref = commit if isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit) else 'main'
    url = f'https://github.com/edgedelta/pipeline-performance-bench/blob/{ref}/docs/report-prompt.md'
    return (f'> **AI disclosure:** This benchmark and reporting code were developed with AI assistance. '
            f'See the [prompt excerpts and reporting requirements]({url}). '
            'Reports are generated automatically from measured data by Python templates; '
            'no AI model writes or modifies the results during a benchmark run.\n\n')
