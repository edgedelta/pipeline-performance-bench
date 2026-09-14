#!/usr/bin/env python3
"""Exercise two isolated Cribl fleet configurations concurrently, without EC2."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import cribl_fleet

ROOT = Path(__file__).resolve().parents[1]


def exercise(case, root):
    directory = root / case
    shutil.copytree(ROOT / 'pipelines/cribl', directory)
    state = directory / 'fleet.json'
    try:
        fleet = cribl_fleet.create(state)
        env = dict(os.environ, CRIBL_WORKER_GROUP=fleet)
        for args in [('create-http-input',), ('create-s3-destination',), ('create-pipeline',), ('create-route',), ('update-pipeline', case + '.json'), ('cleanup-all',)]:
            result = subprocess.run([str(directory / 'cribl-api.sh'), *args], cwd=directory, env=env, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f'Isolated fleet check failed at {args[0]} (exit {result.returncode})')
        return fleet
    finally:
        cribl_fleet.delete(state)


if __name__ == '__main__':
    # Keep state on failure so cleanup can be retried by the workflow's always step.
    root = ROOT / '.fleet-check'
    root.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda case: exercise(case, root), ['filter', 'mask']))
    assert len(set(ids)) == 2
    print('Two concurrent isolated fleet configurations deployed and removed successfully; no EC2 resources created.')
