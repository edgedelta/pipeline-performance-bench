"""Build a portable chart using the same colors and controls as the public log site."""
import argparse
import json
from pathlib import Path
from .model import VENDORS


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('root',type=Path)
    ap.add_argument('output',type=Path)
    args=ap.parse_args()
    data={}
    for vendor in VENDORS:
        path=args.root/vendor/'results.json'
        if path.exists(): data[vendor]=json.loads(path.read_text())
    template=Path(__file__).with_name('chart.html').read_text()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(template.replace('__DATA__',json.dumps(data).replace('</','<\\/')))


if __name__=='__main__': main()
