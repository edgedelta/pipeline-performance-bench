"""Provision isolated hosts, run request-rate benchmarks, and always destroy them."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .rps import Host


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output', default='otlp-rps-results')
    ap.add_argument('--instance-type', default='c8i.8xlarge')
    args, extra=ap.parse_known_args()
    root=Path(__file__).resolve().parents[1]
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
            install=tmp/'install.tgz'
            subprocess.run(['tar','-czf',str(install),'-C',str(root),'scripts','otlpbench/install.sh','otlpbench/requirements.txt'],check=True)
            subprocess.run([sys.executable,str(root/'tools/fetch_red.py'),str(tmp/'red')],check=True,env={**os.environ,'RED_VERSION':'3.15.0'})
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
    finally:
        if (infra/'terraform.tfstate').exists():print(tf('destroy','-auto-approve','-var=instance_type='+args.instance_type),flush=True)


if __name__=='__main__':main()
