#!/usr/bin/env python3
"""Local Linux binary integration test; no AWS, cloud endpoints or benchmark results."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from fixed import phase

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='fixed-loadgen-validation-') as tmp:
    subprocess.run(['docker','run','--rm','--platform','linux/amd64','--network','none','-v',f'{root}/.loadgen-build:/build:ro','-v',f'{root}/payloads:/payloads:ro','-v',f'{tmp}:/output','--entrypoint','/build/loadgen-rust','ubuntu:24.04','--endpoint','http://127.0.0.1:1','--number','1','--workers','256','--timeout','30s','--max-retries','2','--retry-ambiguous','--fixed-rate','200','--fixed-calibration','--fixed-warmup','1s','--total-time','3s','--fixed-payload-file','/payloads/fixed-nginx.ndjson','--fixed-output','/output/local-validation.json'],check=True,timeout=60)
    raw=json.loads((Path(tmp)/'local-validation.json').read_text())
    metrics=phase(raw,3,require_agent=False)
    assert 180<=metrics['offered_logs_per_second']<=204,metrics
    assert metrics['errors']==0 and metrics['acknowledged_logs_per_second']>=180,metrics
    assert metrics['generator_cpu_percent'] is not None and metrics['generator_avg_memory_mb']>0,metrics
    assert raw['agent_backlog'] is None
    print('PASS local Linux fixed-mode binary: global offered/acknowledged rates, window accounting, generator CPU/RSS, raw JSON parsing. Validation only; not an agent benchmark.')
