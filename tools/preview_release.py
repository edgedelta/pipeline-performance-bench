#!/usr/bin/env python3
"""Create clearly synthetic raw fixtures and a local preview; never contacts GitHub/AWS."""
import argparse
import hashlib
import json
from pathlib import Path
from fixed import COUNTERS, RATES
from summarize import VENDORS, CASES, UNSUPPORTED, summarize
from publish_release import release_notes

ROOT = Path(__file__).resolve().parents[1]


def sample(seconds, cpu=100, mem=200_000_000):
    return {'elapsed_seconds': seconds, 'agent_cpu_usage_usec': int(seconds*cpu*10000), 'agent_memory_bytes': int(mem), 'generator_cpu_usage_usec': int(seconds*200_000), 'generator_rss_bytes': 80_000_000, 'host_busy_ticks': int(seconds*200), 'host_total_ticks': int(seconds*800)}


def raw_phase(rate, duration, cpu, mem, capacity=False):
    p = {k: 0 for k in COUNTERS}
    offered = int(rate*duration); ack = int(offered*.8) if capacity else offered
    p.update(duration_seconds=duration, scheduled_logs=offered, dispatched_logs=offered, offered_logs=offered, acknowledged_logs=ack, errors=offered-ack, backpressure=offered-ack, http_drain_seconds=.02, mean_response_latency_ms=1.0, canceled=False, http_status_counts={'200': ack, **({'429': offered-ack} if capacity else {})}, resource_samples=[sample(t, cpu, mem*(1+t/duration*.1)) for t in range(duration+1)])
    return p


def raw_loadgen(rate, sha, cpu=100, mem=200_000_000, calibration=False, capacity=False):
    warmup, duration = (2, 10) if calibration else (10, 60)
    return {'schema_version': 2, 'target_logs_per_second': rate, 'workers': 256, 'payload_sha256': sha, 'warmup_seconds': warmup, 'configured_measurement_seconds': duration, 'request_timeout_seconds': 30, 'max_retries': 2, 'retry_ambiguous': True, 'calibration': calibration, 'agent_backlog': None, 'agent_backlog_stability': 'not measured', 'warmup': raw_phase(rate, warmup, cpu, mem), 'measurement': raw_phase(rate, duration, cpu, mem, capacity)}


def write(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def create_fixture(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    corpus = (ROOT/'payloads/fixed-nginx.ndjson').read_bytes(); sha = hashlib.sha256(corpus).hexdigest()
    (directory/'fixed-nginx.ndjson').write_bytes(corpus)
    write(directory/'provenance.json', {'synthetic': True, 'schema_version': 2, 'benchmark_commit': 'a'*40, 'rust_commit': None, 'rust_release': {'version': 'SYNTHETIC', 'binary_sha256': 'b'*64}, 'loadgen_version': 'SYNTHETIC fixed-rate fixture', 'loadgen': {'retry_ambiguous': True}, 'execution_mode': 'SYNTHETIC: parallel separate agent instances, sequential scenarios/tiers', 'fixed_rate': {'targets': RATES, 'workers': 256, 'warmup_seconds': 10, 'measurement_seconds': 60, 'agent_drain_seconds': 60, 'tolerance': .02, 'payload_sha256': sha}})
    (directory/'versions.csv').write_text('agent,version\n'+''.join(f'{v},SYNTHETIC-FIXTURE\n' for v in VENDORS))
    limits = {'cpu_max': 'max 100000', 'cpuset_cpus_effective': '0-7', 'memory_max_bytes': 'max', 'memory_high_bytes': 'max', 'cpu_weight': '100', 'effective_cpu_quota_cores': None, 'effective_memory_limit_bytes': None, 'unlimited_cpu_quota': True, 'unlimited_memory': True, 'main_process_cpu_affinity': '0-7', 'cpu_ancestors_observed': True, 'memory_ancestors_observed': True}
    for i, v in enumerate(VENDORS):
        h = {'synthetic': True, 'runtime': {'observed': {'instance_type': 'SYNTHETIC c8i.2xlarge', 'region': 'SYNTHETIC us-west-2', 'availability_zone': 'SYNTHETIC AZ', 'logical_cpus': 8, 'cpu_model': 'Illustrative fixture CPU (not inspected)', 'architecture': 'x86_64', 'cores_per_socket': 4, 'sockets': 1, 'threads_per_core': 2, 'installed_memory_bytes': 16_000_000_000, 'os': 'SYNTHETIC Ubuntu 24.04', 'kernel': 'SYNTHETIC kernel', 'storage_devices': [{'type': 'disk', 'size': 100_000_000_000, 'model': 'SYNTHETIC EBS'}], 'virtualization': 'none', 'load_generator_shares_instance': True}, 'topology': 'Separate instance per agent; parallel agents; sequential scenarios/tiers', 'generator_limits': limits, 'generator_cpu_affinity': '0-7'}, 'published': {'source': 'SYNTHETIC: not queried from AWS', 'memory_mib': 16384, 'vcpu': {'DefaultVCpus': 8, 'DefaultCores': 4, 'DefaultThreadsPerCore': 2}, 'network': {'description': 'SYNTHETIC', 'cards': [{'BaselineBandwidthInGbps': 2.5, 'PeakBandwidthInGbps': 10}]}, 'ebs': {'BaselineBandwidthInMbps': 1000, 'MaximumBandwidthInMbps': 5000, 'BaselineThroughputInMBps': 125, 'MaximumThroughputInMBps': 625, 'BaselineIops': 3000, 'MaximumIops': 10000}, 'volumes': [{'VolumeType': 'gp3', 'Size': 100, 'Iops': 3000, 'Throughput': 125}]}}
        write(directory/f'hardware_{v}.json', h)
        for rate in RATES:
            cal = raw_loadgen(rate, sha, calibration=True); cal['synthetic'] = True
            write(directory/f'{v}_{rate}.calibration.json', cal)
        for c in CASES:
            if (v,c) in UNSUPPORTED: continue
            (directory/f'{v}_{c}.log').write_text('SYNTHETIC FIXTURE — NOT REAL MEASUREMENTS\n'+''.join(f'Starting loadgen with {w} workers\n[STATS] current: 80000 logs/sec | avg: 79000 logs/sec | total: 4740000 | errors: 0 | backpressure: 0 | connection_errors: 0 | retry_attempts: 0 | recovered_requests: 0 | ambiguous_deliveries: 0\n[MONITOR - TARGET] pid: 1 | cpu: 200.0% | memory: 200.0MB\nFinished loadgen with {w} workers\n' for w in [80,100,120]))
            for rate in RATES:
                raw = raw_loadgen(rate, sha, cpu=50+rate/500+i*10, mem=100_000_000+i*20_000_000, capacity=rate==75000 and i%2==0)
                write(directory/f'{v}_{c}_{rate}.fixed.json', {'synthetic': True, 'schema_version': 2, 'vendor': v, 'scenario': c, 'target_logs_per_second': rate, 'complete': True, 'service_unchanged': True, 'agent_drain_observation_seconds': 60, 'agent_backlog_before': None, 'agent_backlog_after': None, 'limits': limits, 'generator_limits': limits, 'loadgen': raw})
    return directory


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('directory', type=Path); a = p.parse_args()
    create_fixture(a.directory)
    data = summarize(a.directory)
    preview = a.directory/'release-notes.md'
    preview.write_text(release_notes((a.directory/'report.md').read_text(), 'https://example.invalid/SYNTHETIC-NOT-A-REAL-RUN', data))
    print(preview.resolve())
