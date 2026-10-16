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
    if vendor == 'cribl' and scenario in ('pass-through','filter','enrich','mask','sample','aggregate'):
        action = ''
        if scenario == 'filter': action = 'items = items.filter(p => !(p.attributes || []).some(a => a.key === "route" && a.value.stringValue === "health"));'
        if scenario in ('enrich','mask'):
            key,value = ('bench.enriched','yes') if scenario=='enrich' else ('secret','REDACTED')
            action = f'for (const p of items) {{ p.attributes = (p.attributes || []).filter(a => a.key !== "{key}"); p.attributes.push({{key:"{key}",value:{{stringValue:"{value}"}}}}); }}'
        if scenario == 'sample': action = 'items = items.filter(p => parseInt(p.traceId.slice(-1),16) < 8);'
        key,value = ('bench.enriched','yes') if scenario=='enrich' else ('secret','REDACTED')
        action = ''
        if scenario == 'filter': action = 'items = items.filter(p => attr(p,"route") !== "health");'
        if scenario in ('enrich','mask'): action = f'for (const p of items) put(p,"{key}","{value}");'
        if scenario == 'sample': action = 'items = items.filter(p => parseInt(String(p.trace_id || p.traceId).slice(-1),16) < 8);'
        if scenario == 'aggregate': action = """const groups=new Map(); for (const p of items) { const attrs=p.attributes||{}; const a=Array.isArray(attrs)?attrs.filter(a=>a.key!=='host'):Object.fromEntries(Object.entries(attrs).filter(([k])=>k!=='host')); const key=JSON.stringify([p.time_unix_nano??p.timeUnixNano,a]); const val=Number(p.as_int??p.asInt??p.as_double??p.asDouble); if (!groups.has(key)) {const q={...p,attributes:a}; delete q.as_int;delete q.asInt;delete q.as_double;delete q.asDouble;q[('time_unix_nano' in p)?'as_double':'asDouble']=val;groups.set(key,q);} else {const q=groups.get(key);q[('time_unix_nano' in p)?'as_double':'asDouble']+=val;} } items=Array.from(groups.values());"""
        code = """function attr(p,k) { const a=p.attributes||{}; if (!Array.isArray(a)) return a[k]; const x=a.find(x=>x.key===k); return x && (x.value.string_value ?? x.value.stringValue); }
function put(p,k,v) { if (!Array.isArray(p.attributes)) { p.attributes=p.attributes||{}; p.attributes[k]=v; } else { const snake=p.attributes.some(a=>a.value && 'string_value' in a.value); p.attributes=p.attributes.filter(a=>a.key!==k); p.attributes.push({key:k,value:snake?{string_value:v}:{stringValue:v}}); } }
function visit(o) { if (!o || typeof o !== 'object') return; for (const k of Object.keys(o)) { if (k.startsWith('__')) continue; if (['spans','data_points','dataPoints'].includes(k) && Array.isArray(o[k])) { let items=o[k]; """+action+""" o[k]=items; } else if (Array.isArray(o[k])) { for(const child of o[k]) visit(child); } else visit(o[k]); } }
visit(__e);"""
        c = {'cribl.yml': {'api': {'host':'127.0.0.1','port':9420}, 'workers': {'count':1,'minimum':1}}, 'inputs.yml': {'inputs': {'in_system_metrics': {'disabled':True}, 'in_system_state': {'disabled':True}, 'in_windows_metrics': {'disabled':True}, 'bench': {'type':'open_telemetry','host':'127.0.0.1','port':4317,'protocol':'grpc','otlpVersion':'1.3.1','extractSpans':False,'extractMetrics':False,'tls':{'disabled':True},'sendToRoutes':False,'connections':[{'output':'bench','pipeline':'bench'}]}}}, 'outputs.yml': {'outputs': {'bench': {'type':'open_telemetry','protocol':'http','endpoint':'http://127.0.0.1:14318','otlpVersion':'1.3.1','preserveNativeAnyValue':True,'httpCompress':'none','flushPeriodSec':.1,'concurrency':4,'systemFields':[]}}}, 'pipelines/bench/conf.yml': {'functions': [] if scenario=='pass-through' else [{'id':'code','filter':'true','conf':{'code':code}}]}}
        return yaml.safe_dump(c,sort_keys=False), None
    if vendor == 'vector' and scenario in ('pass-through','filter','enrich','mask','sample','aggregate'):
        c = {'data_dir': '/tmp/vector-otlp-bench', 'sources': {'in': {'type': 'opentelemetry', 'grpc': {'address': '127.0.0.1:4317'}, 'http': {'address': '127.0.0.1:4318'}, 'use_otlp_decoding': True}}, 'sinks': {'out': {'type': 'opentelemetry', 'inputs': ['in.'+signal], 'protocol': {'type': 'http', 'uri': 'http://127.0.0.1:14318/v1/'+signal, 'encoding': {'codec': 'otlp'}, 'batch': {'max_events': 512, 'timeout_secs': 0.1}}}}}
        if scenario != 'pass-through':
            target = 'm.sum.dataPoints' if signal=='metrics' else 's.spans'
            action = ''
            if scenario=='filter': action = f'{target} = filter(array!({target})) -> |_, p| {{ length(filter(array!(p.attributes)) -> |_, a| {{ a.key == "route" && a.value.stringValue == "health" }}) == 0 }}'
            if scenario in ('enrich','mask'):
                k,v = ('bench.enriched','yes') if scenario=='enrich' else ('secret','REDACTED')
                action = f'{target} = map_values(array!({target})) -> |p| {{ p.attributes = filter(array!(p.attributes)) -> |_, a| {{ a.key != "{k}" }}; p.attributes = push(p.attributes, {{"key":"{k}","value":{{"stringValue":"{v}"}}}}); p }}'
            if scenario=='sample': action = f'{target} = filter(array!({target})) -> |_, p| {{ match(sha2(string!(p.traceId)), r\'[0-7]$\') }}'
            if scenario=='aggregate': action = 'groups = {}; for_each(array!(m.sum.dataPoints)) -> |_, p| { a = filter(array!(p.attributes)) -> |_, a| { a.key != "host" }; key = encode_json([p.timeUnixNano,a]); value = to_float(p.asInt) ?? to_float(p.asDouble) ?? 0.0; previous = get(groups,[key]) ?? null; if previous == null { p.attributes=a; del(p.asInt); p.asDouble=value; groups=set!(groups,[key],p) } else { previous.asDouble = float!(previous.asDouble)+value; groups=set!(groups,[key],previous) } }; m.sum.dataPoints=values(groups)'
            code = '.resourceMetrics = map_values(array!(.resourceMetrics)) -> |r| { r.scopeMetrics = map_values(array!(r.scopeMetrics)) -> |s| { s.metrics = map_values(array!(s.metrics)) -> |m| { '+action+'; m }; s }; r }' if signal=='metrics' else '.resourceSpans = map_values(array!(.resourceSpans)) -> |r| { r.scopeSpans = map_values(array!(r.scopeSpans)) -> |s| { '+action+'; s }; r }'
            c['transforms']={'process':{'type':'remap','inputs':['in.'+signal],'source':code}}
            c['sinks']['out']['inputs']=['process']
        return yaml.safe_dump(c,sort_keys=False),None
    if vendor == 'fluentbit' and (scenario in ('pass-through','enrich','filter') or signal == 'traces' and scenario in ('enrich','mask','sample','tail')):
        source = {'name': 'opentelemetry', 'listen': '127.0.0.1', 'port': 4317}
        p = []
        if scenario in ('enrich','mask'):
            p = [{'name': 'content_modifier', 'context': 'span_attributes', 'action': 'upsert', 'key': 'bench.enriched' if scenario=='enrich' else 'secret', 'value': 'yes' if scenario=='enrich' else 'REDACTED'}]
        if scenario == 'sample': p = [{'name': 'sampling', 'type': 'probabilistic', 'sampling_settings': {'sampling_percentage': 50}}]
        if scenario == 'tail': p = [{'name': 'sampling', 'type': 'tail', 'sampling_settings': {'decision_wait': '1s', 'max_traces': 100000}, 'conditions': [{'type': 'status_code', 'status_codes': ['ERROR']}]}]
        if scenario == 'filter':
            p = [{'name':'metrics_selector','context':'delete_label_value','label':'route health'}] if signal=='metrics' else [{'name':'sampling','type':'tail','sampling_settings':{'decision_wait':'1s','max_traces':100000},'conditions':[{'type':'string_attribute','key':'route','values':['api']}]}]
        if signal == 'metrics' and scenario == 'enrich': p = [{'name': 'labels', 'insert': 'bench.enriched yes'}]
        if p: source['processors'] = {signal: p}
        return yaml.safe_dump({'service': {'flush': 1, 'log_level': 'info'}, 'pipeline': {'inputs': [source], 'outputs': [{'name': 'opentelemetry', 'match': '*', 'host': '127.0.0.1', 'port': 14318, 'metrics_uri': '/v1/metrics', 'traces_uri': '/v1/traces', 'tls': 'off'}]}},sort_keys=False), None
    if vendor == 'fluentd' and scenario in ('pass-through','filter','enrich','mask','sample','aggregate'):
        transform = ''
        if scenario != 'pass-through':
            action = ''
            if scenario=='filter': action = 'items.reject! { |p| p.fetch("attributes",[]).any? { |a| a["key"]=="route" && a.dig("value","stringValue")=="health" } }'
            if scenario in ('enrich','mask'):
                k,v = ('bench.enriched','yes') if scenario=='enrich' else ('secret','REDACTED')
                action = f'items.each {{ |p| p["attributes"].reject! {{ |a| a["key"]=="{k}" }}; p["attributes"] << {{"key"=>"{k}","value"=>{{"stringValue"=>"{v}"}}}} }}'
            if scenario=='sample': action = 'items.select! { |p| p["traceId"][-1].to_i(16) < 8 }'
            if scenario=='aggregate': action = 'items.replace(items.group_by { |p| [p["timeUnixNano"],p["attributes"].reject { |a| a["key"]=="host" }] }.map { |key,ps| q=ps.first.dup; q["attributes"]=key[1]; q.delete("asInt"); q["asDouble"]=ps.sum { |p| (p["asInt"] || p["asDouble"]).to_f }; q })'
            body = 'x["resourceMetrics"].each { |r| r["scopeMetrics"].each { |s| s["metrics"].each { |m| items=m["sum"]["dataPoints"]; '+action+' } } }' if signal=='metrics' else 'x["resourceSpans"].each { |r| r["scopeSpans"].each { |s| items=s["spans"]; '+action+' } }'
            expression = 'x=JSON.parse(record["message"]); '+body+'; JSON.generate(x)'
            transform = '<filter otlp.**>\n  @type record_transformer\n  enable_ruby true\n  <record>\n    message ${'+expression+'}\n  </record>\n</filter>\n'
        return '<source>\n  @type opentelemetry\n  tag otlp.${type}\n  <grpc>\n    bind 127.0.0.1\n    port 4317\n  </grpc>\n</source>\n'+transform+'<match otlp.**>\n  @type opentelemetry\n  <http>\n    endpoint http://127.0.0.1:14318\n  </http>\n  <buffer>\n    flush_mode interval\n    flush_interval 0.1s\n    flush_thread_count 4\n  </buffer>\n</match>\n', None
    return None, 'Native scenario adapter pending; this is not an unsupported-vendor claim.'
