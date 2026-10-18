import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import fetch_otlp_reports


class DailyPagesTest(unittest.TestCase):
    def test_pair_is_verified_before_replacing_either_dataset(self):
        for corrupt in [False, True]:
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'published'
                out.mkdir()
                for signal in ['metrics', 'traces']:
                    (out / f'{signal}.json').write_text('previous')
                def download(args, check):
                    destination = Path(args[args.index('--dir') + 1])
                    sums = []
                    for signal in ['metrics', 'traces']:
                        data = json.dumps(dict(signal=signal, profile='full')).encode()
                        sums.append(f'{hashlib.sha256(data).hexdigest()}  {signal}.json\n')
                        if corrupt and signal == 'traces': data += b'corruption'
                        (destination / f'{signal}.json').write_bytes(data)
                    (destination / 'SHA256SUMS').write_text(''.join(sums))
                releases = json.dumps([dict(tagName='20261019-091700'), dict(tagName='otlp-20261019-091700')])
                with patch.object(fetch_otlp_reports.subprocess, 'check_output', return_value=releases), patch.object(fetch_otlp_reports.subprocess, 'run', side_effect=download):
                    if corrupt:
                        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                            fetch_otlp_reports.fetch('owner/repo', out)
                        self.assertEqual((out / 'metrics.json').read_text(), 'previous')
                        self.assertEqual((out / 'traces.json').read_text(), 'previous')
                    else:
                        fetch_otlp_reports.fetch('owner/repo', out)
                        for signal in ['metrics', 'traces']:
                            self.assertEqual(json.loads((out / f'{signal}.json').read_text())['signal'], signal)


if __name__ == '__main__':
    unittest.main()
