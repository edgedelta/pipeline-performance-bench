"""Native agent configurations; missing adapters are not vendor capability claims."""
import yaml


def config(vendor, signal, scenario):
    if vendor in ('otelcol', 'bindplane'):
        processors = {}
        if scenario == 'filter':
            processors['filter/bench'] = {signal: {'datapoint' if signal == 'metrics' else 'span': ['attributes["route"] == "health"']}}
        if scenario in ('enrich', 'mask'):
            statement = 'set(attributes["bench.enriched"], "yes")' if scenario == 'enrich' else 'set(attributes["secret"], "REDACTED")'
            processors['transform/bench'] = {('metric' if signal == 'metrics' else 'trace')+'_statements': [{'context': 'datapoint' if signal == 'metrics' else 'span', 'statements': [statement]}]}
        if scenario in ('aggregate', 'combined'):
            processors['metricstransform/bench'] = {'transforms': [{'include': 'bench.requests', 'action': 'update', 'operations': [{'action': 'aggregate_labels', 'label_set': ['route'], 'aggregation_type': 'sum'}]}]}
        if scenario in ('rollup', 'combined'):
            processors['interval/bench'] = {'interval': '60s'}
        if scenario == 'sample':
            processors['probabilistic_sampler/bench'] = {'sampling_percentage': 50, 'hash_seed': 22}
        if scenario == 'tail':
            processors['tail_sampling/bench'] = {'decision_wait': '1s', 'num_traces': 100000, 'policies': [{'name': 'errors', 'type': 'status_code', 'status_code': {'status_codes': ['ERROR']}}]}
        processors['batch'] = {'timeout': '100ms', 'send_batch_size': 512, 'send_batch_max_size': 512}
        c = {'receivers': {'otlp': {'protocols': {'grpc': {'endpoint': '127.0.0.1:4317'}}}}, 'processors': processors, 'exporters': {'otlphttp': {'endpoint': 'http://127.0.0.1:14318', 'compression': 'none', 'retry_on_failure': {'enabled': False}, 'sending_queue': {'enabled': False}}}, 'service': {'pipelines': {signal: {'receivers': ['otlp'], 'processors': list(processors), 'exporters': ['otlphttp']}}}}
        if scenario == 'metrics':
            c['connectors'] = {'spanmetrics': {'namespace': 'traces.span.metrics', 'metrics_flush_interval': '1s', 'histogram': {'unit': 'ms', 'explicit': {'buckets': ['5ms', '10ms', '25ms', '50ms']}}}}
            c['service']['pipelines'] = {'traces': {'receivers': ['otlp'], 'exporters': ['spanmetrics']}, 'metrics': {'receivers': ['spanmetrics'], 'exporters': ['otlphttp']}}
        return yaml.safe_dump(c, sort_keys=False), None
    if vendor in ('red', 'edgedelta'):
        p = []
        dtype = ['metric' if signal == 'metrics' else 'trace']
        if scenario == 'metrics':
            return None, 'Span-to-metrics adapter pending; extract_metric is log-oriented.'
        if scenario == 'filter': p = [{'type': 'ottl_filter', 'data_types': dtype, 'condition': 'attributes["route"] == "health"', 'filter_mode': 'exclude'}]
        if scenario in ('enrich', 'mask'):
            statement = 'set(attributes["bench.enriched"], "yes")' if scenario == 'enrich' else 'set(attributes["secret"], "REDACTED")'
            p = [{'type': 'ottl_transform', 'data_types': dtype, 'statements': statement}]
        if scenario in ('aggregate', 'rollup', 'combined'):
            group = ['resource["service.name"]', 'resource["bench.batch"]', 'attributes["route"]']
            if scenario == 'rollup': group.append('attributes["host"]')
            p = [{'type': 'aggregate_metric', 'data_types': dtype, 'aggregate_metric_rules': [{'conditions': ['true'], 'interval': '10s' if scenario == 'aggregate' else '1m', 'aggregation_type': 'sum', 'keep_only_group_by_keys': True, 'group_by': group}]}]
        if scenario == 'sample': p = [{'type': 'sample', 'data_types': dtype, 'percentage': 50, 'field_paths': ['trace.id'], 'pass_through_on_failure': False}]
        if scenario == 'sample' and vendor == 'red': p = [{'type': 'ottl_filter', 'data_types': dtype, 'condition': 'EDXSample(50, trace.id)', 'filter_mode': 'include'}]
        if scenario == 'tail': p = [{'type': 'tail_sample', 'data_types': dtype, 'decision_interval': '1s', 'sampling_policies': [{'name': 'errors', 'policy_type': 'status_code', 'status_codes': ['ERROR']}]}]
        c = {'version': 'v3', 'settings': {'tag': 'otlp-benchmark', 'item_buffer_flush_interval': '100ms', 'archive_flush_interval': '1s', 'archive_max_byte_limit': '1MB'}, 'nodes': [{'name': 'in', 'type': 'otlp_input', 'protocol': 'grpc', 'port': 4317}, {'name': 'process', 'type': 'sequence', 'processors': p}, {'name': 'out', 'type': 'otlp_output', 'protocol': 'http', 'endpoint': '127.0.0.1', 'port': 14318, 'compression': 'uncompressed'}], 'links': [{'from': 'in', 'to': 'process'}, {'from': 'process', 'to': 'out'}]}
        return yaml.safe_dump(c, sort_keys=False), None
    if vendor == 'cribl' and scenario in ('pass-through','filter','enrich','mask','sample'):
        action = ''
        if scenario == 'filter': action = 'items = items.filter(p => !(p.attributes || []).some(a => a.key === "route" && a.value.stringValue === "health"));'
        if scenario in ('enrich','mask'):
            key,value = ('bench.enriched','yes') if scenario=='enrich' else ('secret','REDACTED')
            action = f'for (const p of items) {{ p.attributes = (p.attributes || []).filter(a => a.key !== "{key}"); p.attributes.push({{key:"{key}",value:{{stringValue:"{value}"}}}}); }}'
        if scenario == 'sample': action = 'items = items.filter(p => parseInt(p.traceId.slice(-1),16) < 8);'
        code = ('for (const r of __e.resourceMetrics || []) { for (const s of r.scopeMetrics || []) { for (const m of s.metrics || []) { let items=m.sum.dataPoints; '+action+' m.sum.dataPoints=items; } } }') if signal=='metrics' else ('for (const r of __e.resourceSpans || []) { for (const s of r.scopeSpans || []) { let items=s.spans; '+action+' s.spans=items; } }')
        c = {'cribl.yml': {'api': {'host':'127.0.0.1','port':9420}, 'workers': {'count':1,'minimum':1}}, 'inputs.yml': {'inputs': {'in_system_metrics': {'disabled':True}, 'in_system_state': {'disabled':True}, 'in_windows_metrics': {'disabled':True}, 'bench': {'type':'open_telemetry','host':'127.0.0.1','port':4317,'protocol':'grpc','otlpVersion':'1.3.1','extractSpans':False,'extractMetrics':False,'tls':{'disabled':True},'sendToRoutes':False,'connections':[{'output':'bench','pipeline':'bench'}]}}}, 'outputs.yml': {'outputs': {'bench': {'type':'open_telemetry','protocol':'http','endpoint':'http://127.0.0.1:14318','otlpVersion':'1.3.1','preserveNativeAnyValue':True,'httpCompress':'none','flushPeriodSec':.1,'concurrency':4,'systemFields':[]}}}, 'pipelines/bench/conf.yml': {'functions': [] if scenario=='pass-through' else [{'id':'code','filter':'true','conf':{'code':code}}]}}
        return yaml.safe_dump(c,sort_keys=False), None
    if vendor == 'vector' and scenario == 'pass-through':
        return yaml.safe_dump({'data_dir': '/tmp/vector-otlp-bench', 'sources': {'in': {'type': 'opentelemetry', 'grpc': {'address': '127.0.0.1:4317'}, 'http': {'address': '127.0.0.1:4318'}, 'use_otlp_decoding': True}}, 'sinks': {'out': {'type': 'opentelemetry', 'inputs': ['in.'+signal], 'protocol': {'type': 'http', 'uri': 'http://127.0.0.1:14318/v1/'+signal, 'encoding': {'codec': 'otlp'}, 'batch': {'max_events': 512, 'timeout_secs': 0.1}}}}}, sort_keys=False), None
    if vendor == 'fluentbit' and (scenario in ('pass-through','enrich') or signal == 'traces' and scenario in ('enrich','mask','sample','tail')):
        source = {'name': 'opentelemetry', 'listen': '127.0.0.1', 'port': 4317}
        p = []
        if scenario in ('enrich','mask'):
            p = [{'name': 'content_modifier', 'context': 'span_attributes', 'action': 'upsert', 'key': 'bench.enriched' if scenario=='enrich' else 'secret', 'value': 'yes' if scenario=='enrich' else 'REDACTED'}]
        if scenario == 'sample': p = [{'name': 'sampling', 'type': 'probabilistic', 'sampling_settings': {'sampling_percentage': 50}}]
        if scenario == 'tail': p = [{'name': 'sampling', 'type': 'tail', 'sampling_settings': {'decision_wait': '1s', 'max_traces': 100000}, 'conditions': [{'type': 'status_code', 'status_codes': ['ERROR']}]}]
        if signal == 'metrics' and scenario == 'enrich': p = [{'name': 'labels', 'insert': 'bench.enriched yes'}]
        if p: source['processors'] = {signal: p}
        return yaml.safe_dump({'service': {'flush': 1, 'log_level': 'info'}, 'pipeline': {'inputs': [source], 'outputs': [{'name': 'opentelemetry', 'match': '*', 'host': '127.0.0.1', 'port': 14318, 'metrics_uri': '/v1/metrics', 'traces_uri': '/v1/traces', 'tls': 'off'}]}},sort_keys=False), None
    if vendor == 'fluentd' and scenario == 'pass-through':
        return '<source>\n  @type opentelemetry\n  tag otlp.${type}\n  <grpc>\n    bind 127.0.0.1\n    port 4317\n  </grpc>\n</source>\n<match otlp.**>\n  @type opentelemetry\n  <http>\n    endpoint http://127.0.0.1:14318\n  </http>\n  <buffer>\n    flush_mode interval\n    flush_interval 0.1s\n    flush_thread_count 4\n  </buffer>\n</match>\n', None
    return None, 'Native scenario adapter pending; this is not an unsupported-vendor claim.'
