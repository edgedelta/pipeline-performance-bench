"""SYNTHETIC search evidence; no AWS or actual service invocations."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'benchmark_scripts')]
import capacity
import check_results
import check_short
import fixed
import parallel
import preview_release as fixture
import publish_release
import run_capacity
import summarize


class CapacityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = fixture.create_fixture(Path(self.temp.name)/'20260916_180000', rust_throughput=True)
        self.provenance = json.loads((self.directory/'provenance.json').read_text())

    def get(self, vendor='red', case='pass-through'):
        return capacity.summarize(self.directory, vendor, case, self.provenance)

    def edit(self, name, callback):
        path=self.directory/name; raw=json.loads(path.read_text()); callback(raw);fixture.write(path,raw)

    def test_search_paths_and_selected_measurement_share_fixed_evidence(self):
        rust=self.get(); self.assertEqual(rust['probe_rates'], [200000,250000])
        self.assertEqual(rust['avg'],250000);self.assertTrue(rust['ceiling_reached'])
        self.assertFalse(rust['agent_maximum_established']);self.assertIsNone(rust['peak'])
        go=self.get('edgedelta');self.assertEqual(go['probe_rates'],[200000])
        self.assertEqual(go['selected_target'],125000); self.assertFalse(go['ceiling_reached'])
        fixed_tier=fixed.tier(self.directory,'edgedelta','pass-through',125000,self.provenance['fixed_rate']['payload_sha256'])
        self.assertEqual(go['measurement'],fixed_tier)
        otel=self.get('otelcol');self.assertEqual(otel['probe_rates'],[1000,2500,5000]);self.assertEqual(otel['avg'],5000)
        cribl=self.get('cribl');self.assertEqual(cribl['probe_rates'],[1000,2500]);self.assertEqual(cribl['avg'],1000)
        fb=self.get('fluentbit');self.assertEqual(fb['probe_rates'],[]);self.assertEqual(fb['avg'],25000)

    def test_missing_tampered_incomplete_and_unexplained_probe_rejected(self):
        faults=[('red_pass-through_250000.fixed.json',lambda r:r.update(complete=False)),
                ('red_pass-through.capacity.json',lambda r:r.update(probe_rates=[200000])),
                ('red_pass-through_200000.fixed.json',lambda r:r['loadgen'].update(workers=128)),
                ('red_pass-through_200000.fixed.json',lambda r:r['limits'].update(cpu_max='100000 100000')),
                ('red_pass-through_200000.fixed.json',lambda r:r.pop('generator_limits')),
                ('red_250000.calibration.json',lambda r:r.update(generator_version='wrong'))]
        for name,mutate in faults:
            with self.subTest(name=name):
                path=self.directory/name;original=path.read_text();self.edit(name,mutate)
                self.assertEqual(self.get()['status'],'invalid');path.write_text(original)
        p=self.directory/'red_pass-through_250000.fixed.json';p.unlink()
        self.assertEqual(self.get()['status'],'invalid')
        self.edit('red_pass-through.capacity.json', lambda r:r.update(complete=False))
        self.assertEqual(self.get()['status'],'invalid')

    def test_generator_limitation_is_not_reported_as_agent_capacity(self):
        self.edit('red_250000.calibration.json',lambda r:r.update(measurement=fixture.raw_phase(250000,10,100,200000000,capacity=True)))
        result=self.get();self.assertEqual(result['avg'],200000)
        self.assertTrue(result['generator_uncertainty']);self.assertFalse(result['ceiling_reached'])
        self.assertEqual(result['trials'][-1]['status'],'generator_limited')

    def test_no_passing_probe_is_reportable_but_never_zero_throughput(self):
        self.edit('cribl_pass-through_1000.fixed.json', lambda r:r['loadgen'].update(measurement=fixture.raw_phase(1000,60,100,200000000,capacity=True)))
        (self.directory/'cribl_pass-through_2500.fixed.json').unlink()
        self.edit('cribl_pass-through.capacity.json',lambda r:r.update(probe_rates=[1000]))
        result=self.get('cribl');self.assertEqual(result['status'],'no_sustained_rate');self.assertIsNone(result['avg'])
        self.assertIsNone(result['highest_sustained_target'])

    def test_short_search_reuses_only_two_fixed_tiers(self):
        # Recreate fixture from its initial historical source before converting to short.
        other=fixture.create_fixture(Path(self.temp.name)/'20260916_180001')
        fixture.add_rust_search(other,'short')
        p=json.loads((other/'provenance.json').read_text());p['shards']={'red':{}}
        fixture.write(other/'provenance.json',p)
        result=capacity.summarize(other,'red','pass-through',p)
        self.assertEqual(result['probe_rates'],[]);self.assertEqual(len(result['trials']),2)
        self.assertEqual(result['avg'],125000)
        check_short.validate(other)
        self.assertNotIn('legacy throughput windows',(other/'short-validation.md').read_text())
        with self.assertRaisesRegex(ValueError,'Short validation'):check_results.validate(other)

    def test_report_keeps_highlights_and_never_claims_old_go_method(self):
        data=summarize.summarize(self.directory);before=copy.deepcopy(data)
        body=publish_release.release_notes((self.directory/'report.md').read_text(),'https://example.invalid',data)
        self.assertIn('**250,000** †',body);self.assertIn('🔹',body)
        self.assertNotIn('Go for best-tested',body);self.assertNotIn('three measured worker',body)
        self.assertIn('not proven maximum agent capacities',body)
        self.assertIn('SYNTHETIC',body);self.assertEqual(data,before)
        self.assertIn('Rust sustained-throughput search',(self.directory/'report.md').read_text())
        self.assertEqual(data['aggregation'],'highest-passing-acknowledged-rate')
        self.assertIsNone(data['vendors']['red']['peak'][0])
        for scenario in data['scenarios'].values():
            if scenario['status']=='ok':
                passed=[t['acknowledged_logs_per_second'] for t in scenario['trials'] if t['status']=='ok']
                self.assertEqual(scenario['avg'],max(passed))

    def test_throughput_resources_use_actual_ack_rate_and_same_selected_window(self):
        def adjust(raw):
            p=raw['loadgen']['measurement']
            ack=14992560  # SYNTHETIC: 249,876/sec, not the configured 250,000 target.
            p.update(dispatched_logs=ack, offered_logs=ack, acknowledged_logs=ack,
                     expired_before_dispatch_logs=p['scheduled_logs']-ack, http_status_counts={'200':ack},
                     resource_samples=[fixture.sample(t,cpu=207.3,mem=120000000*(1+t/60*.2)) for t in range(61)])
        self.edit('red_pass-through_250000.fixed.json',adjust)
        data=summarize.summarize(self.directory)
        self.assertAlmostEqual(data['scenarios']['red/pass-through']['avg'],249876)
        body=publish_release.release_notes((self.directory/'report.md').read_text(),'https://example.invalid',data)
        section=body.split('### Pass-Through — best sustained throughput')[1].split('### Filter — best sustained throughput')[0]
        row=next(r for r in section.splitlines() if 'Edge Delta (Rust)' in r)
        self.assertIn('**249,876** † | 207.3 | 132.0 | 144.0 |',row)
        self.assertNotIn('250,000',row)
        self.assertIn('120,538 | 1,893',row)
        self.assertIn('Avg CPU %',section);self.assertIn('Peak memory MB',section)
        self.assertIn('actual acknowledged logs divided by measured seconds',body)

    def test_each_throughput_scenario_sorts_by_its_own_measurement(self):
        data=summarize.summarize(self.directory)
        data['scenarios']['vector/filter']['avg']=260123.4  # SYNTHETIC rendering input only.
        data['scenarios']['edgedelta/filter'].update(status='invalid',avg=999999)
        body=publish_release.release_notes((self.directory/'report.md').read_text(),'https://example.invalid',data)
        section=body.split('### Filter — best sustained throughput')[1].split('### Mask — best sustained throughput')[0]
        rows=[r for r in section.splitlines() if r.startswith('| ')][1:]
        self.assertIn('🏆 **Vector**',rows[0]);self.assertIn('**260,123**',rows[0])
        self.assertIn('Edge Delta (Rust)',rows[1])
        invalid=next(r for r in rows if 'Edge Delta (Go)' in r)
        self.assertIn('| Invalid | N/A | N/A | N/A | N/A | N/A |',invalid)
        self.assertNotIn('🏆',invalid)

    def test_publication_assets_include_probe_evidence_and_no_legacy_logs(self):
        with self.assertRaisesRegex(ValueError,'Synthetic'):check_results.validate(self.directory)
        # Only remove markers in isolated test fixtures to exercise the real evidence gate.
        for p in self.directory.glob('*.json'):
            raw=json.loads(p.read_text());raw.pop('synthetic',None);fixture.write(p,raw)
        data=check_results.validate(self.directory)
        sums=(self.directory/'SHA256SUMS').read_text()
        self.assertIn('red_pass-through_250000.fixed.json',sums)
        self.assertIn('red_250000.calibration.json',sums)
        self.assertIn('red_pass-through.capacity.json',sums)
        self.assertNotIn('.log\n',sums)
        self.assertEqual(len(sums.splitlines()),len(set(sums.splitlines())))
        (self.directory/'red_pass-through_250000.fixed.json').unlink()
        with self.assertRaisesRegex(ValueError,'Capacity probe'):check_results.validate(self.directory)
        self.assertFalse((self.directory/'SHA256SUMS').exists())

    def test_runner_reuses_standard_tiers_and_probes_only_once(self):
        calls=[];states={r:{'status':'ok'} for r in fixed.RATES+[200000,250000]}
        def execute(vendor,scenario,rates=None):calls.append(rates)
        original=Path.cwd()
        try:
            os.chdir(self.temp.name)
            Path('fixed-nginx.ndjson').write_bytes(b'{}\n')
            with patch.dict(os.environ,BENCHMARK_PROFILE='full'),patch.object(run_capacity.run_fixed,'run',side_effect=execute),patch.object(run_capacity.fixed,'tier',side_effect=lambda root,v,c,r,p:states[r]):
                run_capacity.run('red','filter')
            self.assertEqual(calls,[None,[200000],[250000]])
            manifest=json.loads(Path('benchmark_results/red_filter.capacity.json').read_text())
            self.assertTrue(manifest['complete']);self.assertEqual(manifest['probe_rates'],[200000,250000])
            calls.clear();states[200000]={'status':'capacity_limited'}
            with patch.dict(os.environ,BENCHMARK_PROFILE='full'),patch.object(run_capacity.run_fixed,'run',side_effect=execute),patch.object(run_capacity.fixed,'tier',side_effect=lambda root,v,c,r,p:states[r]):run_capacity.run('red','filter')
            self.assertEqual(calls,[None,[200000]])
            with patch.object(run_capacity.run_fixed,'run',side_effect=RuntimeError('failed probe')):
                with self.assertRaisesRegex(RuntimeError,'failed probe'):run_capacity.run('red','filter')
            self.assertFalse(json.loads(Path('benchmark_results/red_filter.capacity.json').read_text())['complete'])
        finally:os.chdir(original)

    def test_parallel_merge_retains_search_evidence_and_rejects_missing_probe(self):
        import shutil
        source=Path(self.temp.name)/'shards';source.mkdir()
        matrix={'include':[{'vendor':v,'cases':'pass-through'} for v in ['red','vector']]}
        for v in ['red','vector']:
            shard=source/v;shard.mkdir()
            for f in self.directory.glob(v+'*'):shutil.copyfile(f,shard/f.name)
            shutil.copyfile(self.directory/'fixed-nginx.ndjson',shard/'fixed-nginx.ndjson')
            (shard/'versions.csv').write_text(f'agent,version\n{v},SYNTHETIC\n')
            p=dict(self.provenance,instance_id=v)
            fixture.write(shard/'provenance.json',p)
            h=json.loads((self.directory/f'hardware_{v}.json').read_text())
            fixture.write(shard/'hardware.json',h['runtime']);fixture.write(shard/'hardware-aws.json',h['published'])
        output=Path(self.temp.name)/'merged'
        parallel.merge(source,output,matrix,require_fixed=True)
        data=json.loads((output/'data.json').read_text())
        self.assertEqual(data['scenarios']['red/pass-through']['avg'],250000)
        self.assertTrue((output/'red_250000.calibration.json').exists())
        self.assertTrue((output/'red_pass-through.capacity.json').exists())
        (source/'red'/'red_pass-through_250000.fixed.json').unlink()
        with self.assertRaisesRegex(ValueError,'Incomplete Rust search'):
            parallel.merge(source,Path(self.temp.name)/'bad',matrix,require_fixed=True)

    def test_fixed_runner_probes_use_identical_windows_and_service_lifecycle(self):
        import run_fixed
        calls=[]
        raw=fixture.raw_loadgen(200000,self.provenance['fixed_rate']['payload_sha256'])
        original=Path.cwd()
        def execute(command,**kwargs):
            calls.append(command)
            if command[0]=='loadgen-rust' and '--fixed-calibration' not in command:
                fixture.write(Path(command[command.index('--fixed-output')+1]),raw)
            return type('Result',(),{'returncode':0})()
        def systemctl(*args):
            field=args[args.index('-p')+1]
            return {'InvocationID':'stable','ActiveState':'active','ControlGroup':'/agent','MainPID':'123'}[field]
        try:
            os.chdir(self.temp.name);Path('fixed-nginx.ndjson').write_bytes(b'{}\n')
            real_read=Path.read_text
            def read(path,*args,**kwargs):
                return '0::/generator' if str(path)=='/proc/self/cgroup' else real_read(path,*args,**kwargs)
            with patch.object(run_fixed.subprocess,'run',side_effect=execute),patch.object(run_fixed,'ready',return_value='stable'),patch.object(run_fixed,'systemctl',side_effect=systemctl),patch.object(run_fixed.Path,'read_text',read),patch.object(run_fixed.collect_machine,'limits',return_value={}),patch.object(run_fixed.collect_machine,'read',return_value='Cpus_allowed_list: 0-7'),patch.object(run_fixed.time,'sleep'),patch.object(run_fixed.fixed,'tier',return_value={'status':'ok','reason':'SYNTHETIC'}):
                run_fixed.run('red','filter',rates=[200000])
            commands=[c for c in calls if c[0]=='loadgen-rust']
            self.assertEqual(len(commands),2)
            for c in commands:
                for flag,value in [('--workers','256'),('--dispatch-mode','workers'),('--fixed-rate','200000'),('--max-retries','2'),('--timeout','30s'),('--number','1')]:self.assertEqual(c[c.index(flag)+1],value)
                self.assertIn('--retry-ambiguous',c)
            self.assertEqual(commands[-1][commands[-1].index('--fixed-warmup')+1],'10s')
            self.assertEqual(commands[-1][commands[-1].index('--total-time')+1],'60s')
            self.assertEqual(commands[-1][commands[-1].index('--fixed-cgroup')+1],'/sys/fs/cgroup/agent')
            self.assertEqual([c[2] for c in calls if c[:2]==['sudo','systemctl']],['stop','start','stop'])
            record=json.loads(Path('benchmark_results/red_filter_200000.fixed.json').read_text())
            self.assertTrue(record['complete']);self.assertTrue(record['service_unchanged'])
        finally:os.chdir(original)

    def test_new_harness_never_launches_legacy_go_sweep(self):
        self.assertNotIn('in throughput fixed;', (ROOT/'run.sh').read_text())
        self.assertEqual((ROOT/'run.sh').read_text().count('for BENCHMARK_MODE in capacity;'),7)
        self.assertIn('run_capacity.py',(ROOT/'benchmark_scripts/trigger_benchmark.sh').read_text())
        self.assertIn('tools/capacity.py',(ROOT/'run.sh').read_text())
