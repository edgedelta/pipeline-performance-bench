"""Build the load ladder page from the same datasets as the signal pages."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    history = json.loads((output / 'data/history.json').read_text())
    runs = [run for run in history if run.get('ladder')]
    if not runs:
        raise ValueError('No measured log ladder available')
    data = {'logs': max(runs, key=lambda run: (run['date'], run['runId']))}
    for signal in ['metrics', 'traces']:
        data[signal] = json.loads((output / signal / 'results.json').read_text())
    template = (ROOT / 'site/ladder/index.html').read_text()
    payload = json.dumps(data).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    destination = output / 'ladder'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'index.html').write_text(template.replace('__DATA__', payload))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
