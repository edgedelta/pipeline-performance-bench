"""Remote, request-rate-based telemetry scenario benchmark controller."""
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


# Runs on a remote host: report when host:port has accepted TCP connections for
# `stable` consecutive one-second probes, or give up after `timeout` seconds.
PROBE = '''import json,socket,sys,time
host,port,stable,timeout=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),float(sys.argv[4])
start=time.monotonic();run=successes=failures=0;ready=False
while time.monotonic()-start<timeout:
    try:
        with socket.create_connection((host,port),timeout=2): ok=True
    except OSError: ok=False
    if ok: successes+=1;run+=1
    else: failures+=1;run=0
    if run>=stable: ready=True;break
    time.sleep(1)
print(json.dumps(dict(ready=ready,successes=successes,failures=failures,seconds=round(time.monotonic()-start,2))))'''


def wait_reachable(host, address, port, stable=3, timeout=60):
    """Probe address:port from `host` (the load generator) until it is stably reachable."""
    return json.loads(host.argv(['python3', '-c', PROBE, address, str(port), str(stable), str(timeout)]))


# Statuses caused by the harness or hosts rather than by the agent under test.
INFRA_FAILURES = {'execution_failed', 'agent_unreachable'}
MAX_ATTEMPTS = 2


def should_retry(status, attempt, attempts=MAX_ATTEMPTS):
    """Retry a measurement once when it failed for an infrastructure reason; never retry a result."""
    return status in INFRA_FAILURES and attempt + 1 < attempts


def run_attempts(measure, prefix, report, save):
    """Run one measurement, retrying once on an infrastructure failure, and record every attempt."""
    prefix = Path(prefix)
    for attempt in range(MAX_ATTEMPTS):
        row = measure()
        if should_retry(row['status'], attempt):
            # Keep the failed attempt's evidence under an attempt-numbered name; the retry starts a fresh agent process.
            for suffix in ['agent.log', 'warmup.json']:
                evidence = prefix.with_name(f'{prefix.name}-{suffix}')
                if evidence.exists(): evidence.rename(prefix.with_name(f'{prefix.name}-attempt{attempt}-{suffix}'))
            report.setdefault('retried', []).append(dict(row, attempt=attempt)); save()
            print(json.dumps({'vendor': row.get('vendor'), 'batch': row.get('batch'), 'rps': row.get('target_rps'), 'status': row['status'], 'attempt': attempt, 'retrying': True}), flush=True)
            continue
        row['attempts'] = attempt + 1
        report['rows'].append(row); save()
        print(json.dumps({'vendor': row.get('vendor'), 'batch': row.get('batch'), 'rps': row.get('target_rps'), 'achieved': row.get('load', {}).get('achieved_rps'),
                          'cpu': row.get('through_delivery', {}).get('cpu_cores'), 'status': row['status'], 'attempts': row['attempts']}), flush=True)
        return row


def matched_output_config(vendor, sink_address, export_connections=1024, scenario="pass-through", signal="metrics"):
    text, _ = config(vendor, signal, scenario)
    cfg = yaml.safe_load(text)
    if vendor == 'red':
        cfg['settings'] = {'tag': 'otlp-benchmark'}
        cfg['nodes'][-1]['endpoint'] = sink_address
    else:
        cfg['receivers']['otlp']['protocols']['grpc']['endpoint'] = '0.0.0.0:4317'
        cfg['exporters']['otlphttp']['endpoint'] = 'http://'+sink_address+':14318'
        cfg['exporters']['otlphttp'].update(max_idle_conns=export_connections, max_idle_conns_per_host=export_connections, max_conns_per_host=export_connections)
        cfg['processors'].pop('batch', None)
        cfg['service']['pipelines'][signal]['processors'] = list(cfg['processors'])
        if not cfg['processors']: cfg.pop('processors')
    if signal == 'traces' and scenario == 'tail':
        # 8k requests/s × 256 traces/request × 1.5s decision delay, with headroom.
        if vendor == 'red':
            cfg['nodes'][1]['processors'][0]['cache'] = {'batch': {'size': 4_000_000}}
        else:
            cfg['processors']['tail_sampling/bench']['num_traces'] = 4_000_000
            cfg['processors']['tail_sampling/bench']['expected_new_traces_per_sec'] = 2_048_000
            cfg['processors']['batch/tail'] = {'timeout': '500ms', 'send_batch_size': 1_000_000, 'send_batch_max_size': 1_000_000}
            cfg['service']['pipelines']['traces']['processors'].append('batch/tail')
    return cfg


def output_batch_matches(snapshot, batch):
    return snapshot['requests'] > 0 and snapshot.get('request_points') == {str(batch): snapshot['requests']} and snapshot['points'] == batch*snapshot['requests']


def trace_verified(scenario, snapshot, accepted):
    c = snapshot.get('trace_checks', {})
    points = snapshot['points']
    if accepted <= 0 or not points or c.get('invalid', 1) or c.get('roots') != c.get('children') or c.get('root_ids') != c.get('child_ids'):
        return False
    if c.get('masked' if scenario == 'mask' else 'private') != points:
        return False
    if scenario == 'sample':
        return .45 <= points / accepted <= .55
    fraction = .75 if scenario == 'filter' else .25 if scenario == 'tail' else 1
    if points != accepted * fraction:
        return False
    if scenario == 'filter': return snapshot['health_points'] == 0
    if scenario == 'tail': return c['error_trace_spans'] == points
    return True


def scenario_verified(scenario, snapshot, accepted, batch, signal='metrics'):
    if signal == 'traces': return trace_verified(scenario, snapshot, accepted)

    expected = accepted * (0.75 if scenario == 'filter' else 1)
    if accepted <= 0 or snapshot['value_sum'] != expected:
        return False
    if scenario in ('aggregate', 'combined'):
        return 0 < snapshot['points'] < accepted and snapshot['host_points'] == 0
    if scenario == 'rollup':
        return 0 < snapshot['points'] < accepted and snapshot['host_points'] == snapshot['points']
    if snapshot['points'] != expected:
        return False
    if scenario == 'filter':
        return snapshot['health_points'] == 0
    if scenario == 'enrich':
        return snapshot['enriched_points'] == snapshot['points']
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--signal', choices=['metrics','traces'], default='metrics')
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
    ap.add_argument('--scenario', choices=['pass-through','filter','enrich','aggregate','rollup','combined','mask','sample','tail'], default='pass-through')
    ap.add_argument('--series-groups', type=int, default=0)
    args = ap.parse_args()
    if args.signal == 'traces' and args.scenario not in ('pass-through','filter','mask','sample','tail'): ap.error('unsupported trace ladder scenario')
    if args.signal == 'metrics' and args.scenario not in ('pass-through','filter','enrich','aggregate','rollup','combined'): ap.error('unsupported metric ladder scenario')
    if args.signal == 'traces' and any(int(b) <= 0 or int(b) % 8 for b in args.batches.split(',')): ap.error('trace batches must be positive multiples of eight')
    reducing = args.scenario in ('aggregate','rollup','combined','tail')
    native_batch = reducing or args.scenario == 'sample'
    fraction = .75 if args.scenario == 'filter' else .25 if args.scenario == 'tail' else 1
    hosts = json.loads(Path(args.hosts).read_text())
    load, agent, sink = (Host(hosts[k]['public'], args.key) for k in ['load', 'agent', 'sink'])
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'schema': 'otlp-rps-v1', 'signal': args.signal, 'scenario': args.scenario, 'series_groups': args.series_groups,
              'seconds': args.seconds, 'connections': args.connections, 'concurrency': args.concurrency,
              'generator': 'Rust', 'sink': 'Rust', 'topology': 'separate load, agent, and sink hosts',
              'output_batch_policy': 'scenario-native reductions; no added rebatching', 'calibration': [], 'rows': []}
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
            '--signal', args.signal, '--fixture', path, '--rps', str(rate), '--seconds', str(seconds), '--connections', str(args.connections),
            '--concurrency', str(args.concurrency), '--timeout-seconds', '30' if args.signal=='traces' else '5', '--sequence-offset', str(offset), '--series-groups', str(args.series_groups)]))
    def drain(expected, timeout=10, by_value=False):
        end = time.monotonic()+timeout
        last_points, stable_since = -1, time.monotonic()
        while True:
            s = snapshot()
            if args.scenario == 'sample' and by_value:
                if s['points'] != last_points: last_points, stable_since = s['points'], time.monotonic()
                elif time.monotonic() - stable_since >= 2: return s
            if s['value_sum' if by_value else 'points'] >= expected or time.monotonic() >= end: return s
            time.sleep(.2)
    sink_pid = int(sink.command('nohup /home/ubuntu/otlp-traffic sink --grpc-addr 0.0.0.0:14317 --http-addr 0.0.0.0:14318 > /home/ubuntu/sink.log 2>&1 < /dev/null & echo $!').strip())
    binaries = {'red': '/opt/red/red', 'otelcol': '/usr/bin/otelcol-contrib', 'bindplane': '/opt/observiq-otel-collector/observiq-otel-collector'}
    try:
        for _ in range(30):
            try: snapshot(); break
            except subprocess.CalledProcessError: time.sleep(.2)
        else: raise RuntimeError('sink did not become ready')
        report['sink_readiness'] = wait_reachable(load, hosts['sink']['private'], 14317)
        if not report['sink_readiness']['ready']: raise RuntimeError('sink not reachable from the load host: '+json.dumps(report['sink_readiness']))
        for batch in map(int, args.batches.split(',')):
            f = fixture(args.signal, batch)
            if args.signal == 'metrics':
                f.resource_metrics[0].resource.attributes[1].value.string_value='00000000000000000000'
            else:
                from .model import attrs
                attrs(f.resource_spans[0].resource.attributes, {'bench.batch': '00000000000000000000'})
                for i, span in enumerate(f.resource_spans[0].scope_spans[0].spans):
                    span.trace_id = b'BENCHID!' + (i//2+1).to_bytes(8, 'big')
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
                        cfg = matched_output_config(vendor, hosts['sink']['private'], args.concurrency, args.scenario, args.signal)
                        path=out/f'{vendor}-{batch}-{rate}-{trial}.yaml'; path.write_text(yaml.safe_dump(cfg,sort_keys=False));agent.upload(path,'/home/ubuntu/agent.yaml')
                        argv=[binaries[vendor],'--config','/home/ubuntu/agent.yaml']
                        if vendor=='bindplane': argv+=['--logging','/opt/observiq-otel-collector/logging.yaml']
                        env=['env','ED_API_KEY=benchmark-local','ED_SKIP_CONF_DOWNLOAD=1','ED_BACKEND_DISABLED=1','ED_DISABLE_CONF_RELOAD=1','ED_COORDINATOR_CLIENT_DISABLED=1','ED_DISABLE_LIVE_CAPTURE=1']
                        def measure():
                            pid=int(agent.argv(['sudo', '-n', 'sh', '-c', 'nohup '+shlex.join(env+argv)+' > /home/ubuntu/agent.log 2>&1 < /dev/null & echo $!']).strip())
                            base={'vendor':vendor,'batch':batch,'target_rps':rate,'trial':trial,'scenario':args.scenario}
                            try:
                                time.sleep(2)
                                version=agent.argv([binaries[vendor],'--version']).strip()
                                digest=agent.argv(['sha256sum',binaries[vendor]]).split()[0]
                                endpoint='http://'+hosts['agent']['private']+':4317'
                                readiness=wait_reachable(load, hosts['agent']['private'], 4317)
                                if not readiness['ready']:
                                    return dict(base,status='agent_unreachable',readiness=readiness,version=version,binary_sha256=digest)
                                sink_call('reset',True)
                                warmup = {'skipped': 'fresh process for stateful windows'}
                                if not reducing:
                                    warm=generate(endpoint,remote_fixture,min(rate,1000),5,10**15)
                                    warm_delivery=drain(warm['accepted_points'] * fraction, by_value=True)
                                    warmup={'load':warm,'delivered':warm_delivery}
                                    (out/f'{vendor}-{batch}-{rate}-{trial}-warmup.json').write_text(json.dumps(warmup,indent=2)+'\n')
                                    if not scenario_verified(args.scenario,warm_delivery,warm['accepted_points'],batch,args.signal):
                                        return dict(base,status='warmup_failed',warmup=warmup,readiness=readiness)
                                    if not native_batch and not output_batch_matches(warm_delivery, batch*3//4 if args.scenario=='filter' else batch):
                                        return dict(base,status='batch_mismatch',output_batch_verified=False,delivered=warm_delivery,readiness=readiness)
                                sink_call('reset',True)
                                before=agent.stats(pid); sink_before=sink.stats(sink_pid)
                                m=generate(endpoint,remote_fixture,rate,args.seconds,10**16)
                                input_end=agent.stats(pid)
                                delivered=drain(m['accepted_points'] * fraction, timeout=75 if reducing else 10, by_value=True)
                                final=agent.stats(pid);sink_final=sink.stats(sink_pid)
                                verified=scenario_verified(args.scenario,delivered,m['accepted_points'],batch,args.signal)
                                status='measured'
                                if m['achieved_rps']<rate*.95 or m['rpc_errors'] or m['rejected_points']:status='input_shortfall'
                                if not verified:status='operation_mismatch'
                                batch_verified=True if native_batch else output_batch_matches(delivered,batch*3//4 if args.scenario=='filter' else batch)
                                if not batch_verified:status='batch_mismatch'
                                return dict(base,version=version,binary_sha256=digest,status=status,load=m,delivered=delivered,input_window=cpu(before,input_end),through_delivery=cpu(before,final),sink_resources=cpu(sink_before,sink_final),sampling_verified=verified if args.scenario=='sample' else None,delivery_verified=(None if args.scenario=='sample' else delivered['value_sum']==m['accepted_points']*fraction),delivery_check='statistical retention and paired trace fingerprints' if args.scenario=='sample' else 'exact output count',output_batch_verified=None if native_batch else batch_verified,operation_verified=verified,warmup=warmup,readiness=readiness)
                            except subprocess.CalledProcessError as error:
                                return dict(base,status='execution_failed',error=str(error))
                            finally:
                                (out/f'{vendor}-{batch}-{rate}-{trial}-agent.log').write_text(agent.argv(['tail','-c','262144','/home/ubuntu/agent.log']))
                                agent.command('sudo -n kill -TERM '+str(pid)+' 2>/dev/null || true')
                                for _ in range(50):
                                    alive = agent.argv(['python3','-c','import psutil,sys; p=psutil.Process(int(sys.argv[1])) if psutil.pid_exists(int(sys.argv[1])) else None; print(bool(p and p.status()!=psutil.STATUS_ZOMBIE))',str(pid)]).strip()
                                    if alive == 'False': break
                                    time.sleep(.1)
                                else:
                                    agent.command('sudo -n kill -KILL '+str(pid)+' 2>/dev/null || true')
                                time.sleep(1)
                        run_attempts(measure, out/f'{vendor}-{batch}-{rate}-{trial}', report, save)
    finally:
        sink.argv(['kill','-TERM',str(sink_pid)]);save()


if __name__=='__main__': main()
