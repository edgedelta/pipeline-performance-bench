#!/usr/bin/env python3
"""Record source provenance without recording credentials or the environment."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from fixed import RATES

root = Path(__file__).resolve().parents[1]
def revision(path):
    result = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()

result = {
    'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'benchmark_commit': revision(root),
    'rust_commit': revision(Path(os.environ.get('RED_SRC_DIR', root.parent / 'red'))) if os.environ.get('RED_BUILD_FROM_SOURCE') == '1' else None,
    'instance_id': os.environ.get('BENCHMARK_INSTANCE_ID'),
    'execution_mode': os.environ.get('BENCHMARK_EXECUTION_MODE', 'sequential'),
    'schema_version': 3,
    'fixed_rate': {'generator': json.loads((root / '.loadgen-build/rust-provenance.json').read_text()), 'stop_after_shortfall': True, 'measurement_order': 'per scenario: throughput then ascending fixed rates', 'targets': RATES, 'workers': 256, 'warmup_seconds': 10, 'measurement_seconds': 60, 'agent_drain_seconds': 60, 'tolerance': 0.02, 'calibration_warmup_seconds': 2, 'calibration_measurement_seconds': 10, 'sampling_interval_seconds': 1, 'maximum_catchup_seconds': 0.005, 'memory_scope': 'whole systemd cgroup v2; decimal MB', 'payload_sha256': sha256(root / 'payloads/fixed-nginx.ndjson')},
    'loadgen_version': '1.1.0+connection-retries.1+fixed-rate.1',
    'loadgen': json.loads((root / '.loadgen-build/provenance.json').read_text()),
    'workers': [80, 100, 120],
    'duration_per_tier_seconds': 60,
    'period': '1ms',
    'instance_type': 'c8i.2xlarge',
    'region': 'us-west-2',
    'pipeline_sha256': {str(p.relative_to(root)): sha256(p) for p in sorted((root / 'pipelines').rglob('*')) if p.is_file()},
}
for env in ['ED_BINARY', 'RED_BINARY']:
    if os.environ.get(env):
        result[env.lower() + '_sha256'] = sha256(Path(os.environ[env]))
if os.environ.get('RED_RELEASE_METADATA'):
    result['rust_release'] = json.loads(Path(os.environ['RED_RELEASE_METADATA']).read_text())
Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
