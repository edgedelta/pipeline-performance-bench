import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(ROOT/'benchmark_scripts'))
import fixed
import collect_machine
import aws_machine
import preview_release as fixture
import summarize
import check_results
import publish_release
import parallel


class FixedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = fixture.create_fixture(Path(self.tmp.name)/'20260915_091700')
        self.sha = hashlib.sha256((self.directory/'fixed-nginx.ndjson').read_bytes()).hexdigest()

    def get(self, rate=10000, vendor='red', case='filter'):
        return fixed.tier(self.directory, vendor, case, rate, self.sha)

    def edit(self, callback, name='red_filter_10000.fixed.json'):
        p=self.directory/name; data=json.loads(p.read_text()); callback(data); fixture.write(p,data)

    def test_metric_formulas_units_and_scope(self):
        t=self.get()
        self.assertEqual(t['status'], 'ok')
        self.assertEqual(t['agent_cpu_percent'], 80)
        self.assertAlmostEqual(t['agent_avg_memory_mb'], 126, places=5)
        self.assertEqual(t['agent_peak_memory_mb'], 132)
        self.assertEqual(t['logs_per_second_per_core'], 12500)
        self.assertEqual(t['cpu_microseconds_per_acknowledged_log'], 80)
        self.assertAlmostEqual(t['logs_per_second_per_mb'], 10000/126, places=5)
        self.assertEqual(t['generator_cpu_percent'],20)
        self.assertIsNone(t['agent_backlog_before'])
        self.assertEqual(t['agent_backlog_stability'], 'not measured')

    def test_time_weighting_not_arithmetic_sample_average(self):
        samples=[fixture.sample(0,100,100_000_000),fixture.sample(1,100,200_000_000),fixture.sample(3,100,400_000_000)]
        m=fixed.resources(samples,3)
        self.assertEqual(m['agent_avg_memory_mb'],250)
        self.assertEqual(m['agent_cpu_percent'],100)

    def test_missing_and_unsupported_are_distinct(self):
        (self.directory/'red_filter_10000.fixed.json').unlink()
        self.assertEqual(self.get()['status'],'missing')
        data=summarize.summarize(self.directory)
        self.assertEqual(data['fixed_throughput']['tiers']['fluentbit/mask/10000']['status'],'unsupported')

    def test_capacity_keeps_metrics_but_excludes_aggregate(self):
        t=self.get(75000,'edgedelta')
        self.assertEqual(t['status'],'capacity_limited')
        self.assertFalse(t['sustains_target'])
        self.assertEqual(t['acknowledged_logs_per_second'],60000)
        data=summarize.summarize(self.directory)
        self.assertEqual(data['fixed_throughput']['common_scenarios'],['pass-through','filter'])
        self.assertIsNone(data['fixed_throughput']['common_scenario_aggregates']['edgedelta/75000']['logs_per_second_per_mb'])
        self.assertEqual(data['fixed_throughput']['common_scenario_aggregates']['red/75000']['status'],'ok')

    def test_generator_calibration_failure_not_agent_capacity(self):
        def fail(raw):
            p=raw['measurement']; p['acknowledged_logs']-=10000;p['offered_logs']-=10000;p['dispatched_logs']-=10000;p['scheduler_missed_logs']+=10000;p['http_status_counts']['200']-=10000
        self.edit(fail,'red_10000.calibration.json')
        self.assertEqual(self.get()['status'],'generator_limited')

    def test_unexplained_under_offering_is_not_agent_capacity(self):
        def fail(raw):
            p=raw['loadgen']['measurement'];p['acknowledged_logs']-=100000;p['offered_logs']-=100000;p['dispatched_logs']-=100000;p['worker_queue_dropped_logs']+=100000;p['http_status_counts']['200']-=100000
        self.edit(fail)
        self.assertEqual(self.get()['status'],'generator_limited')

    def test_ack_window_shortfall_is_capacity(self):
        def fail(raw):
            p=raw['loadgen']['measurement'];p['acknowledged_logs']-=100000;p['acknowledged_after_window']+=100000
        self.edit(fail)
        self.assertEqual(self.get()['status'],'capacity_limited')

    def test_bad_request_is_invalid_configuration(self):
        def fail(raw):
            p=raw['loadgen']['measurement'];p['acknowledged_logs']-=1;p['errors']+=1;p['http_status_counts']['200']-=1;p['http_status_counts']['400']=1
        self.edit(fail)
        self.assertEqual(self.get()['status'],'invalid')
        self.assertIn('configuration',self.get()['reason'])

    def test_invalid_duration_policy_counters_resources_and_restart(self):
        original=json.loads((self.directory/'red_filter_10000.fixed.json').read_text())
        mutations=[lambda r:r.update(complete=False),lambda r:r.update(service_unchanged=False),lambda r:r['loadgen'].update(workers=128),lambda r:r['loadgen'].update(payload_sha256='wrong'),lambda r:r['loadgen']['measurement'].update(duration_seconds=55),lambda r:r['loadgen']['measurement'].update(retry_attempts=-1),lambda r:r['loadgen']['measurement'].update(resource_samples=[]),lambda r:r['loadgen']['measurement'].update(canceled=True),lambda r:r['loadgen']['measurement'].update(client_inflight_after_drain=1),lambda r:r['loadgen']['measurement'].update(acknowledged_logs=999999999),lambda r:r['loadgen']['measurement']['resource_samples'][5].update(agent_cpu_usage_usec=0),lambda r:r['loadgen']['measurement']['resource_samples'][5].update(agent_memory_bytes=float('nan')),lambda r:r['loadgen']['warmup'].update(canceled=True)]
        for mutation in mutations:
            raw=copy.deepcopy(original);mutation(raw);fixture.write(self.directory/'red_filter_10000.fixed.json',raw)
            with self.subTest(mutation=mutation): self.assertEqual(self.get()['status'],'invalid')

    def test_tolerance_boundary(self):
        m={'offered_logs_per_second':10000,'acknowledged_logs_per_second':9800,'errors':0,'backpressure':0}
        self.assertTrue(fixed.attainment(m,10000));m['acknowledged_logs_per_second']=9799;self.assertFalse(fixed.attainment(m,10000))

    def test_recovered_ambiguous_deliveries_do_not_invalidate(self):
        self.edit(lambda r:r['loadgen']['measurement'].update(connection_errors=3,retry_attempts=3,recovered_requests=2,ambiguous_deliveries=2))
        t=self.get();self.assertEqual(t['status'],'ok');self.assertEqual(t['ambiguous_deliveries'],2)

    def test_historical_results_are_not_backfilled(self):
        p=self.directory/'provenance.json';old=json.loads(p.read_text());old.pop('schema_version');old.pop('fixed_rate');old.pop('synthetic');fixture.write(p,old)
        data=summarize.summarize(self.directory)
        self.assertFalse(data['fixed_throughput']['measured'])
        self.assertEqual(data['fixed_throughput']['tiers']['red/filter/10000']['status'],'not_measured')
        self.assertNotIn('logs_per_second_per_mb',data['fixed_throughput']['tiers']['red/filter/10000'])
        self.assertEqual(data['scenarios']['red/filter']['avg'],79000)
        self.assertIn('no extrapolation',(self.directory/'report.md').read_text())

    def test_report_actual_release_body_and_synthetic_gate(self):
        data=summarize.summarize(self.directory);report=(self.directory/'report.md').read_text();body=publish_release.release_notes(report,'https://example.invalid',data)
        for text in ['Hardware and test setup','CPU and memory at fixed rates','Logs/sec/MB','Highest sustained fixed-rate target','Benchmark source','SYNTHETIC FIXTURE','Tested agent versions']:
            self.assertIn(text,body)
        for text in ['Connection Recovery','Comparable aggregate efficiency','Queue dropped','HTTP drain sec']:
            self.assertNotIn(text,body)
            self.assertIn(text,report)
        self.assertLess(len(body.encode()),125000)
        with self.assertRaisesRegex(ValueError,'Synthetic'):check_results.validate(self.directory)
        self.assertFalse((self.directory/'SHA256SUMS').exists())

    def test_concise_release_deduplicates_hardware_without_hiding_differences(self):
        data=summarize.summarize(self.directory)
        report=(self.directory/'report.md').read_text()
        body=publish_release.release_notes(report,'https://example.invalid',data)
        self.assertEqual(body.count('Illustrative fixture CPU (not inspected)'),1)
        self.assertNotIn('<details>',body)
        self.assertNotIn('<summary>',body)
        self.assertIn('### Pass-Through — measured CPU, memory and efficiency',body)
        data['hardware']['vector']['runtime']['observed']['os']='Different OS'
        data['hardware']['red']['runtime']['observed']['os']=None
        body=publish_release.release_notes(report,'https://example.invalid',data)
        row=next(line for line in body.splitlines() if line.startswith('| OS / kernel'))
        self.assertIn('Vector: Different OS',row)
        self.assertIn('Edge Delta (Rust): N/A',row)

    def test_release_sorts_throughput_by_raw_values_and_flags_after_valid_rows(self):
        data=summarize.summarize(self.directory)
        data['scenarios']['vector/pass-through']['avg']=100000.2
        data['scenarios']['red/pass-through']['avg']=100000.1
        data['scenarios']['edgedelta/pass-through'].update(status='errors',avg=200000)
        body=publish_release.release_notes((self.directory/'report.md').read_text(),'https://example.invalid',data)
        overview=body.split('## Best-tested throughput')[1].split('## Highest sustained')[0]
        self.assertLess(overview.index('| Vector |'),overview.index('| Edge Delta (Rust) |'))
        self.assertLess(overview.index('| Fluentd |'),overview.index('| Edge Delta (Go) |'))
        self.assertIn('sorted by pass-through throughput',overview)

    def test_fixed_rows_sort_within_target_and_never_promote_failed_efficiency(self):
        data=summarize.summarize(self.directory)
        tiers=data['fixed_throughput']['tiers']
        tiers['vector/filter/10000']['logs_per_second_per_core']=2000000.2
        tiers['red/filter/10000']['logs_per_second_per_core']=2000000.1
        tiers['edgedelta/filter/10000'].update(status='capacity_limited',logs_per_second_per_core=99999999)
        body=publish_release.release_notes((self.directory/'report.md').read_text(),'https://example.invalid',data)
        section=body.split('### Filter — measured CPU')[1].split('### Mask — measured CPU')[0]
        self.assertLess(section.index('| 10,000 | Vector |'),section.index('| 10,000 | Edge Delta (Rust) |'))
        self.assertLess(section.index('| 10,000 | Fluentd |'),section.index('| 10,000 | Edge Delta (Go) |'))
        self.assertLess(section.index('| 10,000 | Edge Delta (Go) |'),section.index('| 25,000 |'))
        self.assertNotIn('<details>',body)

    def test_concise_release_links_original_assets_and_keeps_data_unchanged(self):
        data=summarize.summarize(self.directory);before=copy.deepcopy(data)
        report=(self.directory/'report.md').read_text()
        body=publish_release.release_notes(report,'https://github.com/edgedelta/pipeline-performance-bench/actions/runs/123',data)
        self.assertIn('/releases/download/20260915-091700/report.md',body)
        self.assertIn('/releases/download/20260915-091700/data.json',body)
        self.assertEqual(data,before)
        self.assertEqual((self.directory/'report.md').read_text(),report)
        self.assertIn('| Edge Delta (Rust) | 79,000 | 79,000 | 79,000 | 79,000 |',body)

    def test_concise_historical_release_does_not_invent_fixed_metrics(self):
        self.edit(lambda r:r.pop('schema_version'),'provenance.json')
        data=summarize.summarize(self.directory)
        body=publish_release.release_notes((self.directory/'report.md').read_text(),'https://example.invalid',data)
        self.assertIn('not measured in this historical result format',body)
        self.assertNotIn('## Highest sustained fixed-rate target',body)
        self.assertNotIn('## CPU and memory at fixed rates',body)

    def realish_fixture_for_gate_test_only(self):
        # Remove fixture markers ONLY inside an ephemeral test directory. No network calls.
        for path in self.directory.glob('*.json'):
            raw=json.loads(path.read_text());raw.pop('synthetic',None);fixture.write(path,raw)

    def test_complete_capacity_suite_assets_and_failed_gate(self):
        self.realish_fixture_for_gate_test_only()
        data=check_results.validate(self.directory)
        files=(self.directory/'SHA256SUMS').read_text().splitlines()
        self.assertEqual(len(files),170) # 26 logs + 4 legacy assets + 104 tiers + 28 calibrations + 7 hardware + corpus
        self.assertTrue(any('red_filter_10000.fixed.json' in f for f in files))
        self.assertEqual(len(data['fixed_throughput']['tiers']),112)
        (self.directory/'red_filter_10000.fixed.json').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):check_results.validate(self.directory)
        self.assertFalse((self.directory/'SHA256SUMS').exists())

    def test_measured_legacy_errors_validate_but_do_not_rank(self):
        self.realish_fixture_for_gate_test_only()
        log=self.directory/'fluentd_filter.log'
        log.write_text(log.read_text().replace('errors: 0 | backpressure:', 'errors: 1 | backpressure:'))
        data=check_results.validate(self.directory)
        self.assertEqual(data['scenarios']['fluentd/filter']['status'],'errors')
        report=(self.directory/'report.md').read_text()
        row=next(line for line in report.splitlines() if line.startswith('| Fluentd | errors |'))
        self.assertTrue(row.endswith('| N/A |'))
        body=publish_release.release_notes(report,'https://example.invalid',data)
        self.assertIn('Completed with request errors; excluded from rankings',body)
        # A truncated run is still rejected, even with errors present.
        log.write_text(log.read_text().replace('Finished loadgen with 120 workers','unfinished'))
        with self.assertRaisesRegex(ValueError,'invalid'):check_results.validate(self.directory)

    def test_mismatched_hardware_or_limits_blocks_publication(self):
        self.realish_fixture_for_gate_test_only()
        self.edit(lambda r:r['runtime']['observed'].update(logical_cpus=4),'hardware_red.json')
        with self.assertRaisesRegex(ValueError,'machine configurations differ'):check_results.validate(self.directory)
        self.edit(lambda r:r['runtime']['observed'].update(logical_cpus=8),'hardware_red.json')
        self.edit(lambda r:r['limits'].update(effective_cpu_quota_cores=1))
        with self.assertRaisesRegex(ValueError,'limits differ'):check_results.validate(self.directory)

    def test_parallel_merge_retains_every_raw_asset(self):
        source=Path(self.tmp.name)/'shards';source.mkdir()
        data=json.loads((self.directory/'provenance.json').read_text())
        for vendor in ['red','vector']:
            d=source/vendor;d.mkdir()
            for p in self.directory.iterdir():
                if p.name.startswith(vendor+'_') or p.name=='fixed-nginx.ndjson':(d/p.name).write_bytes(p.read_bytes())
            h=json.loads((self.directory/f'hardware_{vendor}.json').read_text())
            fixture.write(d/'hardware.json',h['runtime']);fixture.write(d/'hardware-aws.json',h['published'])
            fixture.write(d/'provenance.json',dict(data,instance_id=vendor))
            (d/'versions.csv').write_text(f'agent,version\n{vendor},SYNTHETIC\n')
        output=Path(self.tmp.name)/'merged'
        parallel.merge(source,output,{'include':[{'vendor':v,'cases':'filter'} for v in ['red','vector']]},require_fixed=True)
        self.assertTrue((output/'hardware_red.json').exists())
        self.assertTrue((output/'vector_filter_75000.fixed.json').exists())
        self.assertTrue((output/'red_75000.calibration.json').exists())


class ShortfallTest(unittest.TestCase):
    setUp = FixedTest.setUp
    get = FixedTest.get
    edit = FixedTest.edit
    realish_fixture_for_gate_test_only = FixedTest.realish_fixture_for_gate_test_only
    def shortfall(self):
        def fail(raw):
            p=raw['loadgen']['measurement']
            for k in ['acknowledged_logs','offered_logs','dispatched_logs']: p[k]-=100000
            p['worker_queue_dropped_logs']+=100000;p['http_status_counts']['200']-=100000
        self.edit(fail)

    def skip(self, rate=25000, trigger=10000):
        fixture.write(self.directory/f'red_filter_{rate}.fixed.json', {
            'schema_version':2,'vendor':'red','scenario':'filter','target_logs_per_second':rate,
            'complete':True,'status':'skipped_after_shortfall','payload_sha256':self.sha,
            'trigger_target_logs_per_second':trigger})

    def test_shortfall_publishable_without_claiming_success_or_capacity(self):
        self.realish_fixture_for_gate_test_only();self.shortfall()
        data=check_results.validate(self.directory)
        t=data['fixed_throughput']['tiers']['red/filter/10000']
        self.assertEqual(t['status'],'generator_limited');self.assertFalse(t['comparison_eligible'])
        report=(self.directory/'report.md').read_text()
        body=publish_release.release_notes(report,'https://example.invalid',data)
        self.assertIn('failed to sustain target',body);self.assertIn('bottleneck uncertainty',body)
        self.assertIn('Fail*',body)
        self.assertIn('FAIL — target not sustained / generator_limited',report)
        self.assertGreater(data['fixed_throughput']['outcomes']['failed_target'],0)
        self.edit(lambda r:r['loadgen']['measurement'].update(resource_samples=[]))
        with self.assertRaisesRegex(ValueError,'invalid'):check_results.validate(self.directory)

    def test_skip_keeps_metrics_absent_and_validates_actual_failure(self):
        self.shortfall();self.skip()
        t=self.get(25000);self.assertEqual(t['status'],'skipped_after_shortfall')
        self.assertIsNone(t['sustains_target']);self.assertNotIn('acknowledged_logs_per_second',t)
        (self.directory/'red_filter_10000.fixed.json').unlink()
        self.assertEqual(self.get(25000)['status'],'invalid')

    def test_skip_rejects_success_future_trigger_or_wrong_payload(self):
        self.skip();self.assertEqual(self.get(25000)['status'],'invalid')
        self.shortfall();self.skip(trigger=50000);self.assertEqual(self.get(25000)['status'],'invalid')
        self.skip();self.edit(lambda r:r.update(payload_sha256='wrong'),'red_filter_25000.fixed.json')
        self.assertEqual(self.get(25000)['status'],'invalid')

    def test_highest_sustained_never_inferred_from_skipped(self):
        self.shortfall()
        for rate in [25000,50000,75000]:self.skip(rate)
        data=summarize.summarize(self.directory)
        summary=data['fixed_throughput']['scenario_attainment']['red/filter']
        self.assertIsNone(summary['highest_measured_sustained_target'])
        self.assertEqual(summary['lowest_measured_failed_target'],10000)
        self.assertEqual(data['fixed_throughput']['outcomes']['not_tested_after_shortfall'],3)
        self.assertIn('NOT TESTED / skipped_after_shortfall',(self.directory/'report.md').read_text())

    def test_uncertain_tier_still_requires_limits_and_calibration(self):
        self.realish_fixture_for_gate_test_only();self.shortfall()
        for rate in [25000,50000,75000]:self.skip(rate)
        check_results.validate(self.directory)
        self.edit(lambda r:r.pop('limits'))
        with self.assertRaisesRegex(ValueError,'missing limits'):check_results.validate(self.directory)

    def test_runner_stops_after_shortfall_without_starting_higher_tiers(self):
        import os,subprocess,run_fixed
        previous=os.getcwd();os.chdir(self.directory.parent);self.addCleanup(os.chdir,previous)
        self.directory.rename('benchmark_results');self.directory=Path('benchmark_results')
        Path('fixed-nginx.ndjson').write_bytes((self.directory/'fixed-nginx.ndjson').read_bytes())
        self.shortfall()
        raw=json.loads((self.directory/'red_filter_10000.fixed.json').read_text())['loadgen']
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            if args[0]=='loadgen':Path(args[args.index('--fixed-output')+1]).write_text(json.dumps(raw))
            return subprocess.CompletedProcess(args,0)
        def systemctl(*args):
            if 'ControlGroup' in args:return '/system.slice/red.service'
            if 'ActiveState' in args:return 'active'
            return 'invocation'
        original=Path.read_text
        def read(path,*args,**kwargs):
            return '0::/user.slice/test\n' if str(path)=='/proc/self/cgroup' else original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read),patch.object(run_fixed,'ready',return_value='invocation'),patch.object(run_fixed,'systemctl',side_effect=systemctl),patch.object(run_fixed.collect_machine,'limits',return_value={}),patch.object(run_fixed.subprocess,'run',side_effect=run),patch.object(run_fixed.time,'sleep'),patch.object(run_fixed.time,'monotonic',side_effect=[0,60]):
            run_fixed.run('red','filter')
        self.assertEqual(len([c for c in calls if c[0]=='loadgen']),1)
        for rate in [25000,50000,75000]:self.assertEqual(self.get(rate)['status'],'skipped_after_shortfall')


class HardwareTest(unittest.TestCase):
    def test_memtotal_variation_requires_equal_published_ram_and_small_delta(self):
        def machine(observed, published=16384):
            return {'runtime':{'observed':{'installed_memory_bytes':observed}},'published':{'memory_mib':published}}
        self.assertTrue(fixed.memory_matches({'a':machine(16000000000),'b':machine(16000008192)}))
        self.assertFalse(fixed.memory_matches({'a':machine(16000000000),'b':machine(16001000000)}))
        self.assertFalse(fixed.memory_matches({'a':machine(16000000000),'b':machine(16000008192,32768)}))
        self.assertFalse(fixed.memory_matches({'a':machine(16000000000,None),'b':machine(16000008192,None)}))

    def test_aws_allowlist_no_ids(self):
        values=[{'Reservations':[{'Instances':[{'InstanceType':'c8i.2xlarge','InstanceId':'SECRET-ID','PrivateIpAddress':'SECRET-IP','BlockDeviceMappings':[{'Ebs':{'VolumeId':'SECRET-VOLUME'}}]}]}]}, {'InstanceTypes':[{'VCpuInfo':{'DefaultVCpus':8},'MemoryInfo':{'SizeInMiB':16384},'NetworkInfo':{'NetworkCards':[{'BaselineBandwidthInGbps':2.5,'PeakBandwidthInGbps':10,'NetworkCardIndex':0}]},'EbsInfo':{'EbsOptimizedInfo':{'BaselineBandwidthInMbps':1000,'MaximumBandwidthInMbps':5000}}}]}, {'Volumes':[{'VolumeId':'SECRET-VOLUME','VolumeType':'gp3','Size':100,'Iops':3000,'Throughput':125,'Tags':[{'Value':'SECRET-TAG'}]}]}]
        with patch.object(aws_machine,'aws',side_effect=values):h=aws_machine.specifications('unused','us-west-2')
        self.assertNotIn('SECRET',json.dumps(h))
        self.assertEqual(h['network']['cards'][0]['BaselineBandwidthInGbps'],2.5)
        self.assertEqual(h['volumes'][0]['Throughput'],125)
        with patch.object(aws_machine,'aws',return_value=None):h=aws_machine.specifications('unused','us-west-2')
        self.assertIsNone(h['network']);self.assertIsNone(h['volumes'])

    def test_ancestor_limits_and_unavailable(self):
        values={'/sys/fs/cgroup/system.slice/test.service/cpu.max':'max 100000','/sys/fs/cgroup/system.slice/cpu.max':'200000 100000','/sys/fs/cgroup/system.slice/test.service/memory.max':'max','/sys/fs/cgroup/system.slice/memory.max':'1000000000'}
        with patch.object(collect_machine,'read',side_effect=lambda p:values.get(str(p))):h=collect_machine.limits('/system.slice/test.service')
        self.assertEqual(h['effective_cpu_quota_cores'],2);self.assertEqual(h['effective_memory_limit_bytes'],1e9);self.assertFalse(h['unlimited_cpu_quota'])
        with patch.object(collect_machine,'read',return_value=None):h=collect_machine.limits('/system.slice/test.service')
        self.assertIsNone(h['effective_cpu_quota_cores']);self.assertFalse(h['unlimited_cpu_quota']);self.assertFalse(h['cpu_ancestors_observed'])

    def test_observed_metadata_allowlist(self):
        from io import BytesIO
        identity={'instanceType':'c8i.2xlarge','region':'us-west-2','availabilityZone':'us-west-2a','instanceId':'SECRET','accountId':'SECRET','privateIp':'SECRET'}
        with patch.object(collect_machine,'command',return_value=None),patch.object(collect_machine,'read',return_value=None),patch.object(collect_machine.urllib.request,'urlopen',side_effect=[BytesIO(b'token'),BytesIO(json.dumps(identity).encode())]):h=collect_machine.collect()
        self.assertNotIn('SECRET',json.dumps(h));self.assertEqual(h['observed']['availability_zone'],'us-west-2a');self.assertIsNone(h['observed']['cpu_model'])

class RunnerLifecycleTest(unittest.TestCase):
    def test_failed_loadgen_still_stops_service_and_retains_incomplete_record(self):
        import os
        import subprocess
        import run_fixed
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.getcwd();os.chdir(tmp)
            self.addCleanup(os.chdir,previous)
            Path('fixed-nginx.ndjson').write_text('{}\n')
            root=Path('benchmark_results');root.mkdir()
            (root/'red_10000.calibration.json').write_text('{}')
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                if args[0]=='loadgen':raise subprocess.CalledProcessError(1,args)
                return subprocess.CompletedProcess(args,0)
            def systemctl(*args):
                return '/system.slice/red.service' if 'ControlGroup' in args else '1'
            original_read = Path.read_text
            def proc_read(path, *args, **kwargs):
                return '0::/user.slice/test\n' if str(path) == '/proc/self/cgroup' else original_read(path, *args, **kwargs)
            with patch.object(Path, 'read_text', proc_read), patch.object(run_fixed,'RATES',[10000]),patch.object(run_fixed,'ready',return_value='invocation'),patch.object(run_fixed,'systemctl',side_effect=systemctl),patch.object(run_fixed.collect_machine,'limits',return_value={}),patch.object(run_fixed.subprocess,'run',side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):run_fixed.run('red','filter')
            self.assertFalse(json.loads((root/'red_filter_10000.fixed.json').read_text())['complete'])
            self.assertEqual(calls[-1],['sudo','systemctl','stop','red.service'])
