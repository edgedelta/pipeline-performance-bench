"""Provision isolated hosts, run request-rate benchmarks, and always destroy them."""
import argparse
import concurrent.futures
import json
import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

from .rps import Host


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output', default='otlp-rps-results')
    ap.add_argument('--instance-type', default='c8i.8xlarge')
    ap.add_argument('--red-binary', type=Path, help='Explicit override of the pinned Linux agent binary')
    ap.add_argument('--baseline-red-binary', type=Path, help='Rerun Rust with a baseline binary on the same hosts')
    args, extra=ap.parse_known_args()
    if args.baseline_red_binary and not args.baseline_red_binary.is_file(): ap.error('--baseline-red-binary must exist')
    if args.red_binary and not args.red_binary.is_file(): ap.error('--red-binary must exist')
    root=Path(__file__).resolve().parents[1]
    if not args.red_binary:
        pin=json.loads((root/'otlpbench/red-build.json').read_text())
        args.red_binary=(root/pin['binary']).resolve()
        if not args.red_binary.is_file():
            ap.error('pinned Rust binary is missing; see otlpbench/RPS.md or supply --red-binary')
        digest=hashlib.sha256(args.red_binary.read_bytes()).hexdigest()
        if digest != pin['sha256']:
            ap.error('local Rust binary differs from the pinned build; use --red-binary explicitly to test a new build')
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    infra=root/'otlpbench/infra-rps'
    def tf(*argv):return subprocess.check_output(['terraform','-chdir='+str(infra),*argv],text=True)
    try:
        print(tf('init'),flush=True)
        print(tf('apply','-auto-approve','-var=instance_type='+args.instance_type),flush=True)
        hosts=json.loads(tf('output','-json','hosts'))
        hosts_file=out/'hosts.json';hosts_file.write_text(json.dumps(hosts))
        endpoints={k:Host(v['public'],infra/'otlp-key.pem') for k,v in hosts.items()}
        with tempfile.TemporaryDirectory(prefix='otlp-rps-') as tmp:
            tmp=Path(tmp)
            archive=tmp/'source.tgz'
            subprocess.run(['tar','--exclude=target','-czf',str(archive),'-C',str(root/'otlpbench'),'traffic-rs'],check=True)
            shutil.copy2(archive, out/'measured-harness-source.tgz')
            install=tmp/'install.tgz'
            subprocess.run(['tar','-czf',str(install),'-C',str(root),'scripts','otlpbench/install.sh','otlpbench/requirements.txt'],check=True)
            (tmp/'red').mkdir()
            shutil.copy2(args.red_binary, tmp/'red/red')
            def build():
                s=endpoints['sink'];s.upload(archive,'/tmp/source.tgz')
                s.command('sudo cloud-init status --wait && sudo apt-get update -qq && sudo apt-get -o DPkg::Lock::Timeout=180 install -y -qq build-essential python3-psutil && tar -xzf /tmp/source.tgz && curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup.sh && sh /tmp/rustup.sh -y --profile minimal --default-toolchain 1.98.0 && .cargo/bin/cargo build --release --locked --manifest-path traffic-rs/Cargo.toml && cp traffic-rs/target/release/otlp-traffic /home/ubuntu/otlp-traffic')
                binary=tmp/'otlp-traffic'
                subprocess.run(['scp',*s.opts,'ubuntu@'+s.address+':/home/ubuntu/otlp-traffic',str(binary)],check=True)
                endpoints['load'].upload(binary,'/home/ubuntu/otlp-traffic')
                endpoints['load'].argv(['chmod','+x','/home/ubuntu/otlp-traffic'])
            def agents():
                a=endpoints['agent'];a.upload(install,'/tmp/install.tgz');a.upload(tmp/'red/red','/tmp/red')
                a.command("sudo cloud-init status --wait && mkdir -p bench && cd bench && tar -xzf /tmp/install.tgz && sed -i '/^version=/c\\version=v1.110.1' scripts/install_agent_bindplane.sh && bash otlpbench/install.sh red && bash otlpbench/install.sh otelcol && bash otlpbench/install.sh bindplane && sudo apt-get -o DPkg::Lock::Timeout=180 install -y -qq python3-psutil")
            with concurrent.futures.ThreadPoolExecutor() as pool:
                jobs=[pool.submit(build),pool.submit(agents)]
                for job in jobs:job.result()
            subprocess.run([sys.executable,'-m','otlpbench.rps','--hosts',str(hosts_file),'--key',str(infra/'otlp-key.pem'),'--output',str(out),*extra],cwd=root,check=True)
            if args.baseline_red_binary:
                endpoints['agent'].upload(args.baseline_red_binary, '/tmp/red-baseline')
                endpoints['agent'].command('sudo install -m755 /tmp/red-baseline /opt/red/red')
                subprocess.run([sys.executable,'-m','otlpbench.rps','--hosts',str(hosts_file),'--key',str(infra/'otlp-key.pem'),'--output',str(out/'baseline'),*extra,'--vendors','red'],cwd=root,check=True)
    finally:
        if (infra/'terraform.tfstate').exists():print(tf('destroy','-auto-approve','-var=instance_type='+args.instance_type),flush=True)


if __name__=='__main__':main()
