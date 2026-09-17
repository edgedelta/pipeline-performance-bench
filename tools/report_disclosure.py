"""Describe AI involvement without claiming an LLM generates measurements."""
import re


def disclosure(provenance=None):
    commit = (provenance or {}).get('benchmark_commit', '')
    ref = commit if isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit) else 'main'
    url = f'https://github.com/edgedelta/pipeline-performance-bench/blob/{ref}/docs/report-prompt.md'
    return ('> **Impartial analysis and transparency:** Our goal is to provide impartial, objective '
            'comparisons across agents. We use AI to help develop the benchmark and analysis code, '
            f'and publish the [prompt excerpts and reporting requirements]({url}) so readers can '
            'inspect our instructions, assess potential bias, and challenge the methodology. '
            'Results are calculated from measured data using explicit rules applied across agents. '
            'AI assistance alone does not guarantee objectivity; open methods and reproducible '
            'evidence make the analysis accountable.\n\n')
