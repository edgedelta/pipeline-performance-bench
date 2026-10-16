"""Remote, request-rate-based metrics Pass-Through benchmark controller."""
import argparse
from datetime import datetime, timezone
import json
import shlex
import subprocess
import time
from pathlib import Path

import yaml
from .configs import config
from .model import fixture


def run(argv, **kwargs):
    return subprocess.check_output(argv, text=True, **kwargs)


class Host:
    def __init__(self, address, key):
        self.address = address
        self.opts = ['-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=accept-new',
                     '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15', '-i', str(key)]

    def command(self, command):
        return run(['ssh', *self.opts, 'ubuntu@'+self.address, 'ulimit -n 65536 || exit 1\n'+command])

    def argv(self, args):
        return self.command(shlex.join(args))

    def upload(self, local, remote):
        run(['scp', *self.opts, str(local), 'ubuntu@'+self.address+':'+remote])

    def stats(self, pid):
        code = '''import json,time,psutil,sys
p=psutil.Process(int(sys.argv[1])); ps=[p]+p.children(recursive=True)
print(json.dumps(dict(time=time.monotonic(),cpu=sum(x.cpu_times().user+x.cpu_times().system for x in ps),rss_mb=sum(x.memory_info().rss for x in ps)/1024**2)))'''
        return json.loads(self.argv(['python3', '-c', code, str(pid)]))


def cpu(first, last):
    elapsed = last['time']-first['time']
    return {'cpu_seconds': last['cpu']-first['cpu'], 'elapsed_seconds': elapsed,
            'cpu_cores': (last['cpu']-first['cpu'])/elapsed, 'rss_mb': last['rss_mb']}


def matched_output_config(vendor, sink_address, export_connections=1024):
    text, _ = config(vendor, 'metrics', 'pass-through')
    cfg = yaml.safe_load(text)
    if vendor == 'red':
        cfg['settings'] = {'tag': 'otlp-benchmark'}
        cfg['nodes'][-1]['endpoint'] = sink_address
    else:
        cfg['receivers']['otlp']['protocols']['grpc']['endpoint'] = '0.0.0.0:4317'
        cfg['exporters']['otlphttp']['endpoint'] = 'http://'+sink_address+':14318'
        cfg['exporters']['otlphttp'].update(max_idle_conns=export_connections, max_idle_conns_per_host=export_connections, max_conns_per_host=export_connections)
        cfg.pop('processors')
        cfg['service']['pipelines']['metrics']['processors'] = []
    return cfg


def output_batch_matches(snapshot, batch):
    return snapshot['requests'] > 0 and snapshot.get('request_points') == {str(batch): snapshot['requests']} and snapshot['points'] == batch*snapshot['requests']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hosts', required=True, help='Terraform hosts output JSON')
    ap.add_argument('--key', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--rates', default='10000,100000', help='requests/sec')
    ap.add_argument('--batches', default='1,512', help='points/request')
    ap.add_argument('--vendors', default='red,otelcol,bindplane')
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--connections', type=int, default=64)
    ap.add_argument('--concurrency', type=int, default=1024)
    ap.add_argument('--trials', type=int, default=1)
    args = ap.parse_args()
    hosts = json.loads(Path(args.hosts).read_text())
    load, agent, sink = (Host(hosts[k]['public'], args.key) for k in ['load', 'agent', 'sink'])
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'schema': 'otlp-rps-v1', 'signal': 'metrics', 'scenario': 'pass-through',
              'seconds': args.seconds, 'connections': args.connections, 'concurrency': args.concurrency,
              'generator': 'Rust', 'sink': 'Rust', 'topology': 'separate load, agent, and sink hosts',
              'output_batch_policy': 'preserve input batch; no rebatching', 'calibration': [], 'rows': []}
    report['harness_sha256'] = load.argv(['sha256sum','/home/ubuntu/otlp-traffic']).split()[0]
    if report['harness_sha256'] != sink.argv(['sha256sum','/home/ubuntu/otlp-traffic']).split()[0]:
        raise RuntimeError('load and sink binaries differ')
    report['host_cpu'] = {k: Host(v['public'],args.key).argv(['lscpu','-J']) for k,v in hosts.items()}
    def save(): (out/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    def sink_call(path, post=False):
        return sink.argv(['curl', '-fsS', '--max-time', '10', *(['-X', 'POST'] if post else []), 'http://127.0.0.1:14318/'+path])
    def snapshot(): return json.loads(sink_call('stats'))
    def generate(endpoint, path, rate, seconds, offset):
        return json.loads(load.argv(['/home/ubuntu/otlp-traffic', 'load', '--endpoint', endpoint,
            '--fixture', path, '--rps', str(rate), '--seconds', str(seconds), '--connections', str(args.connections),
            '--concurrency', str(args.concurrency), '--sequence-offset', str(offset)]))
    def drain(expected, timeout=10):
        end = time.monotonic()+timeout
        while True:
            s = snapshot()
            if s['points'] >= expected or time.monotonic() >= end: return s
            time.sleep(.2)
    sink_pid = int(sink.command('nohup /home/ubuntu/otlp-traffic sink --grpc-addr 0.0.0.0:14317 --http-addr 0.0.0.0:14318 > /home/ubuntu/sink.log 2>&1 < /dev/null & echo $!').strip())
    binaries = {'red': '/opt/red/red', 'otelcol': '/usr/bin/otelcol-contrib', 'bindplane': '/opt/observiq-otel-collector/observiq-otel-collector'}
    try:
        for _ in range(30):
            try: snapshot(); break
            except subprocess.CalledProcessError: time.sleep(.2)
        else: raise RuntimeError('sink did not become ready')
        for batch in map(int, args.batches.split(',')):
            f = fixture('metrics', batch)
            f.resource_metrics[0].resource.attributes[1].value.string_value='00000000000000000000'
            fixture_path = out/f'fixture-{batch}.pb'; fixture_path.write_bytes(f.SerializeToString())
            remote_fixture = f'/home/ubuntu/fixture-{batch}.pb'; load.upload(fixture_path, remote_fixture)
            for rate in map(int, args.rates.split(',')):
                sink_call('reset', True)
                start = sink.stats(sink_pid)
                c = generate('http://'+hosts['sink']['private']+':14317', remote_fixture, rate, min(15,args.seconds), 0)
                delivery = drain(c['accepted_points'])
                c.update(batch=batch, sink=delivery, sink_resources=cpu(start,sink.stats(sink_pid)))
                c['passed'] = c['achieved_rps'] >= .95*rate and c['rpc_errors']==0 and c['rejected_points']==0 and delivery['points']==c['accepted_points'] and delivery['value_sum']==c['accepted_points']
                report['calibration'].append(c); save()
                print(json.dumps({'calibration':batch,'rps':rate,'achieved':c['achieved_rps'],'passed':c['passed']}),flush=True)
                if not c['passed']:
                    for vendor in args.vendors.split(','): report['rows'].append({'vendor':vendor,'batch':batch,'target_rps':rate,'status':'harness_limited'})
                    save(); continue
                for vendor in args.vendors.split(','):
                    for trial in range(args.trials):
                        cfg = matched_output_config(vendor, hosts['sink']['private'], args.concurrency)
                        path=out/f'{vendor}-{batch}-{rate}-{trial}.yaml'; path.write_text(yaml.safe_dump(cfg,sort_keys=False));agent.upload(path,'/home/ubuntu/agent.yaml')
                        argv=[binaries[vendor],'--config','/home/ubuntu/agent.yaml']
                        if vendor=='bindplane': argv+=['--logging','/opt/observiq-otel-collector/logging.yaml']
                        env=['env','ED_API_KEY=benchmark-local','ED_SKIP_CONF_DOWNLOAD=1','ED_BACKEND_DISABLED=1','ED_DISABLE_CONF_RELOAD=1','ED_COORDINATOR_CLIENT_DISABLED=1','ED_DISABLE_LIVE_CAPTURE=1']
                        pid=int(agent.argv(['sudo', '-n', 'sh', '-c', 'nohup '+shlex.join(env+argv)+' > /home/ubuntu/agent.log 2>&1 < /dev/null & echo $!']).strip())
                        try:
                            time.sleep(2)
                            version=agent.argv([binaries[vendor],'--version']).strip()
                            digest=agent.argv(['sha256sum',binaries[vendor]]).split()[0]
                            endpoint='http://'+hosts['agent']['private']+':4317'
                            sink_call('reset',True)
                            warm=generate(endpoint,remote_fixture,min(rate,1000),5,10**15)
                            warm_delivery=drain(warm['accepted_points'])
                            warmup={'load':warm,'delivered':warm_delivery}
                            (out/f'{vendor}-{batch}-{rate}-{trial}-warmup.json').write_text(json.dumps(warmup,indent=2)+'\n')
                            if warm['accepted_points']==0 or warm_delivery['points']!=warm['accepted_points'] or warm_delivery['value_sum']!=warm['accepted_points']:
                                report['rows'].append({'vendor':vendor,'batch':batch,'target_rps':rate,'trial':trial,'status':'warmup_failed','warmup':warmup})
                                save(); continue
                            if not output_batch_matches(warm_delivery, batch):
                                report['rows'].append({'vendor':vendor,'batch':batch,'target_rps':rate,'trial':trial,'status':'batch_mismatch','output_batch_verified':False,'delivered':warm_delivery})
                                save(); continue
                            sink_call('reset',True)
                            before=agent.stats(pid); sink_before=sink.stats(sink_pid)
                            m=generate(endpoint,remote_fixture,rate,args.seconds,10**16)
                            input_end=agent.stats(pid)
                            delivered=drain(m['accepted_points'])
                            final=agent.stats(pid);sink_final=sink.stats(sink_pid)
                            verified=delivered['points']==m['accepted_points'] and delivered['value_sum']==m['accepted_points']
                            status='measured'
                            if m['achieved_rps']<rate*.95 or m['rpc_errors'] or m['rejected_points']:status='input_shortfall'
                            if not verified:status='delivery_mismatch'
                            batch_verified=output_batch_matches(delivered,batch)
                            if not batch_verified:status='batch_mismatch'
                            row={'vendor':vendor,'version':version,'binary_sha256':digest,'batch':batch,'target_rps':rate,'trial':trial,'status':status,'load':m,'delivered':delivered,'input_window':cpu(before,input_end),'through_delivery':cpu(before,final),'sink_resources':cpu(sink_before,sink_final),'delivery_verified':verified,'output_batch_verified':batch_verified,'warmup':warmup}
                            report['rows'].append(row);save();print(json.dumps({'vendor':vendor,'batch':batch,'rps':rate,'achieved':m['achieved_rps'],'cpu':row['through_delivery']['cpu_cores'],'status':status}),flush=True)
                        finally:
                            (out/f'{vendor}-{batch}-{rate}-{trial}-agent.log').write_text(agent.argv(['tail','-c','262144','/home/ubuntu/agent.log']))
                            agent.argv(['sudo','-n','kill','-TERM',str(pid)]);time.sleep(1)
    finally:
        sink.argv(['kill','-TERM',str(sink_pid)]);save()


if __name__=='__main__': main()
