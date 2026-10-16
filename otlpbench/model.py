"""Deterministic OTLP fixtures and the scenario contract."""
import hashlib
import time
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.metrics.v1.metrics_pb2 import AGGREGATION_TEMPORALITY_DELTA

VENDORS = {'red': 'Edge Delta (Rust)', 'edgedelta': 'Edge Delta (Go)', 'bindplane': 'Bindplane (Dynatrace)', 'otelcol': 'OpenTelemetry Collector', 'cribl': 'Cribl', 'vector': 'Vector (Datadog)', 'fluentbit': 'Fluent Bit', 'fluentd': 'Fluentd'}
SCENARIOS = {'metrics': ['pass-through', 'filter', 'enrich', 'aggregate', 'rollup', 'combined'], 'traces': ['pass-through', 'filter', 'enrich', 'mask', 'sample', 'tail', 'metrics']}
LABELS = {'pass-through': 'Pass-Through', 'metrics': 'Metrics'}

def attrs(target, values):
    for k, v in values.items():
        p = target.add(key=k)
        if isinstance(v, bool): p.value.bool_value = v
        elif isinstance(v, int): p.value.int_value = v
        else: p.value.string_value = str(v)


def attributes(values):
    return {x.key: getattr(x.value, x.value.WhichOneof('value')) for x in values}


def fixture(signal, batch=512, sequence=0, base=None):
    """Each trace has two spans; delta points have distinct series within a batch."""
    base = base if base is not None else (int(time.time()) // 60 - 2) * 60
    if signal == 'metrics':
        req = ExportMetricsServiceRequest()
        resource = req.resource_metrics.add()
        attrs(resource.resource.attributes, {'service.name': 'bench', 'bench.batch': str(sequence)})
        scope = resource.scope_metrics.add(); scope.scope.name = 'otlpbench'
        metric = scope.metrics.add(name='bench.requests', unit='1')
        metric.sum.aggregation_temporality = AGGREGATION_TEMPORALITY_DELTA
        metric.sum.is_monotonic = True
        for i in range(batch):
            ts = (base + 5 + (i // 64 % 6) * 10) * 10**9
            p = metric.sum.data_points.add(as_int=1, time_unix_nano=ts, start_time_unix_nano=ts-10*10**9)
            attrs(p.attributes, {'host': str(i % 64), 'route': 'health' if i % 4 == 0 else 'api'})
        return req
    req = ExportTraceServiceRequest()
    resource = req.resource_spans.add()
    attrs(resource.resource.attributes, {'service.name': 'bench'})
    scope = resource.scope_spans.add(); scope.scope.name = 'otlpbench'
    for i in range(batch):
        trace = sequence * ((batch + 1)//2) + i//2 + 1
        trace_id = hashlib.sha256(str(trace).encode()).digest()[:16]
        span_id = (i%2 + 1).to_bytes(8, 'big')
        ts = (base * 10**9) + trace * 1000
        s = scope.spans.add(trace_id=trace_id, span_id=span_id, parent_span_id=b'' if i%2 == 0 else (1).to_bytes(8,'big'), name='bench.root' if i%2 == 0 else 'bench.child', kind=2, start_time_unix_nano=ts, end_time_unix_nano=ts+20_000_000)
        s.status.code = 2 if trace % 4 == 0 and i%2 == 1 else 1
        attrs(s.attributes, {'route': 'health' if trace%4 == 0 else 'api', 'secret': 'private@example.test'})
        s.events.add(time_unix_nano=ts+1, name='checkpoint')
        s.links.add(trace_id=b'\x12'*16, span_id=b'\x13'*8)
    return req


def records(signal, request):
    if signal == 'metrics':
        for r in request.resource_metrics:
            for s in r.scope_metrics:
                for m in s.metrics:
                    kind = m.WhichOneof('data')
                    for p in getattr(m, kind).data_points:
                        yield {'signal': signal, 'resource': attributes(r.resource.attributes), 'scope': s.scope.name, 'name': m.name, 'kind': kind, 'temporality': getattr(getattr(m,kind), 'aggregation_temporality', None), 'attributes': attributes(p.attributes), 'time': p.time_unix_nano, 'start': p.start_time_unix_nano, 'value': getattr(p, p.WhichOneof('value')) if kind in ('sum','gauge') else p.count, 'point': p.SerializeToString().hex()}
    else:
        for r in request.resource_spans:
            for s in r.scope_spans:
                for p in s.spans:
                    yield {'signal': signal, 'resource': attributes(r.resource.attributes), 'scope': s.scope.name, 'trace_id': p.trace_id.hex(), 'span_id': p.span_id.hex(), 'parent': p.parent_span_id.hex(), 'name': p.name, 'attributes': attributes(p.attributes), 'time': p.start_time_unix_nano, 'end': p.end_time_unix_nano, 'status': p.status.code, 'events': [x.SerializeToString().hex() for x in p.events], 'links': [x.SerializeToString().hex() for x in p.links]}


def expected(signal, scenario, sent):
    from collections import defaultdict
    result = []
    keep_traces = {r['trace_id'] for r in sent if r.get('status') == 2}
    for original in sent:
        r = dict(original, attributes=dict(original['attributes']), resource=dict(original['resource']))
        r.pop('point', None)
        if scenario == 'filter' and r['attributes'].get('route') == 'health': continue
        if scenario == 'tail' and r['trace_id'] not in keep_traces: continue
        if scenario == 'enrich': r['attributes']['bench.enriched'] = 'yes'
        if scenario == 'mask': r['attributes']['secret'] = 'REDACTED'
        result.append(r)
    if scenario in ('aggregate', 'rollup', 'combined'):
        interval = 60 if scenario in ('rollup','combined') else 10
        groups = defaultdict(list)
        for r in result:
            a = {k:v for k,v in r['attributes'].items() if k != 'host' or scenario == 'rollup'}
            end = (r['time']//(interval*10**9)+1)*interval*10**9
            key = (tuple(sorted(r['resource'].items())), tuple(sorted(a.items())), end)
            groups[key].append(r)
        result = []
        for (resource,a,end), points in groups.items():
            r = dict(points[0], resource=dict(resource), attributes=dict(a), time=end, start=end-interval*10**9, value=sum(x['value'] for x in points))
            result.append(r)
    return result


def validate(signal, scenario, sent, received):
    """Return evidence rather than claiming every configured pipeline is equivalent."""
    from collections import Counter, defaultdict
    import json
    received = [dict(r) for r in received]
    for r in received:
        r.pop('point', None)
        # Edge Delta copies scope identity into attributes in addition to its OTLP scope.
        for key in ['otel.scope.name','otel.scope.version']:
            r['attributes'].pop(key, None)
    if scenario == 'sample':
        original = {(r['trace_id'],r['span_id']):r for r in sent}
        seen = set(); per_trace = defaultdict(set)
        for r in received:
            key=(r['trace_id'],r['span_id'])
            if key not in original or key in seen or r != original[key]: return False, 'sample changed or duplicated a span'
            seen.add(key); per_trace[r['trace_id']].add(r['span_id'])
        if any(len(ids)!=2 for ids in per_trace.values()): return False, 'sample retained an incomplete trace'
        fraction=len(received)/len(sent)
        return .35 <= fraction <= .65, f'trace-ID sample retained {fraction:.1%}; expected approximately 50%'
    if scenario == 'metrics':
        sums = [r for r in received if r['signal']=='metrics' and r['kind']=='sum']
        hists = [r for r in received if r['signal']=='metrics' and r['kind']=='histogram']
        # Cumulative connector exports may repeat; use the latest value per series.
        def totals(rows):
            groups={}
            for r in rows:
                key=(r['name'],tuple(sorted(r['attributes'].items())),tuple(sorted(r['resource'].items())))
                if key not in groups or r['time']>=groups[key]['time']: groups[key]=r
            return sum(r['value'] for r in groups.values())
        ok=totals(sums)==len(sent) and totals(hists)==len(sent)
        return ok, f'span count={len(sent)}, generated counter={totals(sums)}, histogram count={totals(hists)}'
    want=expected(signal,scenario,sent)
    canonical=lambda r: json.dumps(r,sort_keys=True)
    a,b=Counter(map(canonical,want)),Counter(map(canonical,received))
    return a==b, f'expected {len(want)} output records, got {len(received)}; missing={sum((a-b).values())}, unexpected={sum((b-a).values())}'
