import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import cribl_fleet as fleet


class FleetTest(unittest.TestCase):
    def test_lifecycle_and_unique_identity(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(fleet, 'credentials', return_value=('https://test/groups', 'token')), patch.object(fleet, 'request', return_value={}) as request:
            first, second = Path(temp) / 'first.json', Path(temp) / 'second.json'
            a, b = fleet.create(first), fleet.create(second)
            self.assertNotEqual(a, b)
            self.assertTrue(request.call_args.args[3]['isFleet'])
            fleet.delete(first)
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(request.call_args.args[0], 'https://test/groups/' + a)

    def test_failed_create_preserves_cleanup_identity(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(fleet, 'credentials', return_value=('https://test/groups', 'token')), patch.object(fleet, 'request', side_effect=TimeoutError):
            state = Path(temp) / 'state.json'
            with self.assertRaises(TimeoutError): fleet.create(state)
            self.assertTrue(state.exists())
            self.assertTrue(json.loads(state.read_text())['id'].startswith('pipeline-perf-'))

    def test_cannot_delete_shared_fleet(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(fleet, 'credentials', return_value=('https://test/groups', 'token')), patch.object(fleet, 'request') as request:
            state = Path(temp) / 'state.json'
            state.write_text(json.dumps({'id': 'default_fleet', 'base': 'https://test/groups'}))
            with self.assertRaises(ValueError): fleet.delete(state)
            request.assert_not_called()

    def test_failed_delete_preserves_state(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(fleet, 'credentials', return_value=('https://test/groups', 'token')), patch.object(fleet, 'request', return_value={}):
            state = Path(temp) / 'state.json'; fleet.create(state)
            with patch.object(fleet, 'request', side_effect=TimeoutError):
                with self.assertRaises(TimeoutError): fleet.delete(state)
            self.assertTrue(state.exists())
