#!/usr/bin/env python3
"""Capture allowlisted AWS specifications; never write infrastructure IDs."""
import argparse
import json
from pathlib import Path
import subprocess


def aws(*args):
    p = subprocess.run(['aws', *args, '--output', 'json'], capture_output=True, text=True)
    if p.returncode: return None
    return json.loads(p.stdout)


def specifications(instance_id, region):
    instance_data = aws('ec2', 'describe-instances', '--region', region, '--instance-ids', instance_id)
    result = {'source': 'AWS EC2 DescribeInstanceTypes and DescribeVolumes APIs; specifications, not measured bandwidth', 'instance_type': None, 'vcpu': None, 'memory_mib': None, 'network': None, 'ebs': None, 'volumes': None}
    if not instance_data: return result
    instance = instance_data['Reservations'][0]['Instances'][0]
    kind = instance['InstanceType']; result['instance_type'] = kind
    types = aws('ec2', 'describe-instance-types', '--region', region, '--instance-types', kind)
    if types:
        t = types['InstanceTypes'][0]
        result.update(vcpu={k: t.get('VCpuInfo', {}).get(k) for k in ['DefaultVCpus', 'DefaultCores', 'DefaultThreadsPerCore']}, memory_mib=t.get('MemoryInfo', {}).get('SizeInMiB'), processor={k: t.get('ProcessorInfo', {}).get(k) for k in ['SupportedArchitectures', 'SustainedClockSpeedInGhz', 'Manufacturer']}, network={'description': t.get('NetworkInfo', {}).get('NetworkPerformance'), 'cards': [{k: c.get(k) for k in ['BaselineBandwidthInGbps', 'PeakBandwidthInGbps']} for c in t.get('NetworkInfo', {}).get('NetworkCards', [])]}, ebs={k: (t.get('EbsInfo', {}).get('EbsOptimizedInfo') or {}).get(k) for k in ['BaselineBandwidthInMbps', 'MaximumBandwidthInMbps', 'BaselineThroughputInMBps', 'MaximumThroughputInMBps', 'BaselineIops', 'MaximumIops']})
    ids = [b['Ebs']['VolumeId'] for b in instance.get('BlockDeviceMappings', []) if 'Ebs' in b]
    if ids:
        volumes = aws('ec2', 'describe-volumes', '--region', region, '--volume-ids', *ids)
        if volumes: result['volumes'] = [{k: v.get(k) for k in ['VolumeType', 'Size', 'Iops', 'Throughput', 'Encrypted']} for v in volumes['Volumes']]
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('instance_id'); p.add_argument('output', type=Path); p.add_argument('--region', default='us-west-2'); a = p.parse_args()
    a.output.write_text(json.dumps(specifications(a.instance_id, a.region), indent=2) + '\n')
