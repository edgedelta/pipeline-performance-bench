import copy
import unittest
from .model import expected, fixture, records, validate


class ContractTests(unittest.TestCase):
    def test_derived_counters_use_latest_snapshot(self):
        from .receiver import State
        state=State()
        request=fixture('metrics',1)
        metric=request.resource_metrics[0].scope_metrics[0].metrics[0]
        metric.name='traces.span.metrics.calls'
        metric.sum.data_points[0].as_int=3
        state.accept('metrics',request)
        metric.sum.data_points[0].as_int=5
        metric.sum.data_points[0].time_unix_nano+=1
        state.accept('metrics',request)
        metric.sum.data_points[0].as_int=3
        metric.sum.data_points[0].time_unix_nano-=1
        state.accept('metrics',request)
        self.assertEqual(state.snapshot()['derived']['calls'],5)
        state.reset(False)
        self.assertEqual(state.snapshot()['derived']['calls'],0)

    def test_forwarding_is_exact(self):
        for signal in ('metrics','traces'):
            with self.subTest(signal=signal):
                sent=list(records(signal,fixture(signal)))
                self.assertTrue(validate(signal,'pass-through',sent,sent)[0])
                self.assertFalse(validate(signal,'pass-through',sent,sent[:-1])[0])
                self.assertFalse(validate(signal,'pass-through',sent,sent+sent[:1])[0])

    def test_label_deletion_is_not_aggregation(self):
        sent=list(records('metrics',fixture('metrics')))
        wrong=copy.deepcopy(sent)
        for r in wrong: del r['attributes']['host']
        self.assertFalse(validate('metrics','aggregate',sent,wrong)[0])
        right=expected('metrics','aggregate',sent)
        self.assertTrue(validate('metrics','aggregate',sent,right)[0])
        self.assertEqual(sum(r['value'] for r in right),512)

    def test_batching_is_not_rollup(self):
        sent=list(records('metrics',fixture('metrics')))
        self.assertFalse(validate('metrics','rollup',sent,sent)[0])
        for scenario,n in [('aggregate',16),('rollup',128),('combined',4)]:
            with self.subTest(scenario=scenario):
                output=expected('metrics',scenario,sent)
                self.assertEqual(len(output),n)
                self.assertEqual(sum(r['value'] for r in output),512)

    def test_tail_retains_error_trace_parent(self):
        sent=list(records('traces',fixture('traces')))
        right=expected('traces','tail',sent)
        self.assertEqual(len(right),128)
        self.assertTrue(validate('traces','tail',sent,right)[0])
        self.assertFalse(validate('traces','tail',sent,[r for r in sent if r['status']==2])[0])

    def test_sample_requires_complete_unchanged_traces(self):
        sent=list(records('traces',fixture('traces')))
        self.assertTrue(validate('traces','sample',sent,sent[:256])[0])
        with_metadata=copy.deepcopy(sent[:256])
        for r in with_metadata: r['trace_state']='ot=rv:de9c2363dac858;th:8'
        self.assertTrue(validate('traces','sample',sent,with_metadata)[0])
        with_metadata[0]['attributes']['secret']='changed'
        self.assertFalse(validate('traces','sample',sent,with_metadata)[0])
        self.assertFalse(validate('traces','sample',sent,sent[::2])[0])


if __name__=='__main__': unittest.main()
