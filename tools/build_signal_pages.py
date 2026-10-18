"""Build signal routes from saved measurements without running benchmarks."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from otlpbench.ladder_chart import render

REPORTS = {
    'metrics': ROOT / 'data/otlp/2026-10-17/metrics-ladder',
    'traces': ROOT / 'data/otlp/2026-10-18/traces-low',
}


def build(output):
    logs = output / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    html = (output / 'index.html').read_text()
    (logs / 'index.html').write_text(html.replace('<head>', '<head>\n<base href="../" />', 1))
    for signal, report in REPORTS.items():
        destination = output / signal
        destination.mkdir(parents=True, exist_ok=True)
        latest = output / 'data/otlp' / f'{signal}.json'
        source = latest if latest.exists() else report / 'results.json'
        data = json.loads(source.read_text())
        date = data.get('measured_at', report.parent.name)[:10]
        html = render(data)
        nav = '<nav class="signal-nav" aria-label="Telemetry signal">' + ''.join(
            f'<a href="../{name}/"' + (' aria-current="page"' if name == signal else '') + f'>{name.title()}</a>'
            for name in ['logs', 'metrics', 'traces']) + '</nav>'
        html = html.replace('<main><header>', '<link rel="stylesheet" href="../assets/benchmark.css"><main>' + nav + '<header>')
        html = html.replace('LOCAL PREVIEW · ' + signal.upper() + ' · RUST GENERATOR', signal.upper() + ' · BENCHMARK RESULTS')
        html = html.replace('<footer>', f'<p>Measured: {date}. Load names are relative to this signal’s ladder; compare the actual input rates shown above.</p><footer>')
        if signal == 'traces':
            html = html.replace('<details>', '<p>This lower ladder was selected before the run to leave headroom below the slowest prior Tail result (~700 requests/sec). It compares fixed-load efficiency, not maximum capacity. All five scenarios and all three agents are included.</p><details>')
        (destination / 'index.html').write_text(html)
        shutil.copy2(source, destination / 'results.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
