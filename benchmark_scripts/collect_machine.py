#!/usr/bin/env python3
"""Allowlisted runtime facts only: no hostnames, addresses, IDs or credentials."""
import json
import argparse
import os
import platform
from pathlib import Path
import subprocess
import urllib.request


def command(args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def read(path):
    try: return Path(path).read_text().strip()
    except OSError: return None


def limits(cgroup):
    root = Path('/sys/fs/cgroup')
    path = root / cgroup.lstrip('/')
    values = {'cpu_max': read(path / 'cpu.max'), 'cpuset_cpus_effective': read(path / 'cpuset.cpus.effective'), 'memory_max_bytes': read(path / 'memory.max'), 'memory_high_bytes': read(path / 'memory.high'), 'cpu_weight': read(path / 'cpu.weight')}
    cpus, memory = [], []
    cpu_known, memory_known = True, True
    while path == root or root in path.parents:
        cpu = read(path / 'cpu.max'); mem = read(path / 'memory.max')
        if path != root:
            cpu_known = cpu_known and cpu is not None
            memory_known = memory_known and mem is not None
        if cpu:
            fields = cpu.split()
            if len(fields) == 2 and fields[0] != 'max': cpus.append(int(fields[0]) / int(fields[1]))
        if mem and mem != 'max': memory.append(int(mem))
        if path == root: break
        path = path.parent
    values.update(effective_cpu_quota_cores=min(cpus) if cpus else None, effective_memory_limit_bytes=min(memory) if memory else None, unlimited_cpu_quota=not cpus and cpu_known, unlimited_memory=not memory and memory_known)
    values.update(cpu_ancestors_observed=cpu_known, memory_ancestors_observed=memory_known)
    return values


def collect(topology=None):
    lscpu = command(['lscpu', '--json'])
    cpu = {r['field'].rstrip(':'): r['data'] for r in json.loads(lscpu).get('lscpu', [])} if lscpu else {}
    os_release = {}
    for line in (read('/etc/os-release') or '').splitlines():
        key, _, value = line.partition('='); os_release[key] = value.strip('"')
    mem = next((int(line.split()[1]) * 1024 for line in (read('/proc/meminfo') or '').splitlines() if line.startswith('MemTotal:')), None)
    metadata = {'instance_type': None, 'region': None, 'availability_zone': None}
    try:
        req = urllib.request.Request('http://169.254.169.254/latest/api/token', method='PUT', headers={'X-aws-ec2-metadata-token-ttl-seconds': '60'})
        token = urllib.request.urlopen(req, timeout=2).read().decode()
        req = urllib.request.Request('http://169.254.169.254/latest/dynamic/instance-identity/document', headers={'X-aws-ec2-metadata-token': token})
        identity = json.load(urllib.request.urlopen(req, timeout=2))
        metadata = {'instance_type': identity.get('instanceType'), 'region': identity.get('region'), 'availability_zone': identity.get('availabilityZone')}
    except (OSError, ValueError): pass
    own_cgroup = next((line.split(':', 2)[2] for line in (read('/proc/self/cgroup') or '').splitlines() if line.startswith('0::')), None)
    own_affinity = next((line.split(':', 1)[1].strip() for line in (read('/proc/self/status') or '').splitlines() if line.startswith('Cpus_allowed_list:')), None)
    storage = command(['lsblk', '--bytes', '--json', '--output', 'TYPE,SIZE,ROTA,MODEL'])
    return {'schema_version': 1, 'observed': {**metadata, 'logical_cpus': os.cpu_count(), 'cpu_model': cpu.get('Model name'), 'architecture': platform.machine(), 'cores_per_socket': cpu.get('Core(s) per socket'), 'threads_per_core': cpu.get('Thread(s) per core'), 'sockets': cpu.get('Socket(s)'), 'installed_memory_bytes': mem, 'os': os_release.get('PRETTY_NAME'), 'kernel': platform.release(), 'storage_devices': json.loads(storage).get('blockdevices') if storage else None, 'virtualization': command(['systemd-detect-virt']), 'load_generator_shares_instance': True}, 'generator_limits': limits(own_cgroup) if own_cgroup else None, 'generator_cpu_affinity': own_affinity, 'measurement_scope': 'Fixed rate: whole systemd service cgroup v2, including descendants, page cache and kernel memory charges. Best throughput: legacy monitored process CPU and RSS.', 'topology': topology}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--topology'); a = p.parse_args()
    print(json.dumps(collect(a.topology), indent=2))
