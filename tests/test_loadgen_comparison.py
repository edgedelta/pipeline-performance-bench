import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from compare_loadgens import summarize, render, efficiency

class ComparisonTest(unittest.TestCase):
    def test_generator_efficiency_units_and_missing_values(self):
        self.assertEqual(efficiency(dict(acknowledged_logs_per_second=100000,generator_cpu_percent=200,generator_avg_memory_mb=20)),dict(cpu_microseconds_per_ack=20,logs_per_second_per_mb=5000))
        self.assertEqual(efficiency(dict(acknowledged_logs_per_second=0,generator_cpu_percent=None,generator_avg_memory_mb=None)),dict(cpu_microseconds_per_ack=None,logs_per_second_per_mb=None))
    def test_invalid_trials_excluded_not_disguised(self):
        rows=[dict(target=100000,generator='rust',status='measured',sustains_target=False,acknowledged_logs_per_second=60000,generator_cpu_percent=200),dict(target=100000,generator='rust',status='invalid',acknowledged_logs_per_second=999999)]
        r=next(r for r in summarize(rows) if r['generator']=='rust')
        self.assertEqual(r['acknowledged_logs_per_second'],60000)
        self.assertEqual((r['valid_trials'],r['sustained_trials'],r['trials']),(1,0,2))
        self.assertIsNone(r['generator_avg_memory_mb'])
    def test_three_implementations_remain_separate(self):
        rows=[dict(target=200000,generator=name,status='measured',sustains_target=False,acknowledged_logs_per_second=rate) for name,rate in [('go',100),('rust',200),('rust_tasks',300)]]
        result=summarize(rows)
        self.assertEqual([r['generator'] for r in result],['go','rust','rust_tasks'])
        self.assertEqual([r['acknowledged_logs_per_second'] for r in result],[100,200,300])
    def test_render_scope_and_units(self):
        data=dict(environment=dict(architecture='synthetic',logical_cpus=8,memory_bytes=8e9,kernel='fixture',receiver_cpus=[0],generator_cpus=[1]),workers=256,warmup_seconds=2,measurement_seconds=15,repeats=3,summary=[],trials=[])
        report=render(data)
        self.assertIn('not agent throughput results',report)
        self.assertIn('100% = one logical core',report)
        self.assertIn('1,000,000 bytes',report)
        self.assertIn('±2%',report)
