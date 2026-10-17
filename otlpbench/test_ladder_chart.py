"""Checks that report assembly cannot mix loads or hide missing measurements."""
import json
from pathlib import Path
import tempfile
import unittest

from .ladder_chart import SCENARIOS, RATES, VENDORS, collect


class LadderReportTest(unittest.TestCase):
    def populate(self, root):
        for scenario in SCENARIOS:
            path = root / scenario
            path.mkdir()
            rows = [dict(vendor=v, target_rps=r, batch=512, trial=0, status='measured',
                         binary_sha256='measured-binary') for r in RATES for v in VENDORS]
            (path / 'results.json').write_text(json.dumps(dict(rows=rows, calibration=[])))

    def test_loads_remain_distinct_and_enrich_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.populate(root)
            report = collect(root, 'source', 'measured-binary')
            self.assertEqual(len(report['rows']), 60)
            self.assertNotIn('enrich', report['scenarios'])
            for scenario in SCENARIOS:
                for vendor in VENDORS:
                    self.assertEqual([r['target_rps'] for r in report['rows']
                                      if r['scenario'] == scenario and r['vendor'] == vendor], RATES)

    def test_missing_measurements_are_pending_only_in_partial_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.populate(root)
            path = root / 'rollup/results.json'
            raw = json.loads(path.read_text())
            raw['rows'].pop()
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, 'missing case: rollup/8000/bindplane'):
                collect(root, 'source', 'measured-binary')
            report = collect(root, 'source', 'measured-binary', allow_partial=True)
            pending = [r for r in report['rows'] if r['status'] == 'pending']
            self.assertEqual([(r['scenario'], r['target_rps'], r['vendor']) for r in pending],
                             [('rollup', 8000, 'bindplane')])
            self.assertNotIn('load', pending[0])

    def test_duplicate_cases_and_wrong_binaries_are_rejected(self):
        for mutation, message in [('duplicate', 'duplicate case'), ('binary', 'binary does not match')]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.populate(root)
                path = root / 'filter/results.json'
                raw = json.loads(path.read_text())
                if mutation == 'duplicate':
                    raw['rows'].append(dict(raw['rows'][0]))
                else:
                    raw['rows'][0]['binary_sha256'] = 'different-binary'
                path.write_text(json.dumps(raw))
                with self.assertRaisesRegex(ValueError, message):
                    collect(root, 'source', 'measured-binary')


if __name__ == '__main__':
    unittest.main()
