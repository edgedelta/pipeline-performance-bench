"""Local OTLP destination with an explicit correctness-capture mode."""
import gzip
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import grpc
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2 as metrics, metrics_service_pb2_grpc as mg
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2 as traces, trace_service_pb2_grpc as tg
from .model import records


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset(False)

    def reset(self, capture):
        with self.lock:
            self.capture = capture
            self.data = []
            self.counts = {'metrics': 0, 'traces': 0}

    def accept(self, signal, request):
        if signal == 'metrics':
            n = sum(len(getattr(m, m.WhichOneof('data')).data_points) for r in request.resource_metrics for s in r.scope_metrics for m in s.metrics)
        else:
            n = sum(len(s.spans) for r in request.resource_spans for s in r.scope_spans)
        with self.lock:
            self.counts[signal] += n
            if self.capture:
                self.data.extend(records(signal, request))

    def snapshot(self):
        with self.lock:
            return {'counts': dict(self.counts), 'records': list(self.data)}


def serve():
    state = State()
    class Metrics(mg.MetricsServiceServicer):
        def Export(self, request, context):
            state.accept('metrics', request)
            return metrics.ExportMetricsServiceResponse()
    class Traces(tg.TraceServiceServicer):
        def Export(self, request, context):
            state.accept('traces', request)
            return traces.ExportTraceServiceResponse()
    class HTTP(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def reply(self, body, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self.reply(json.dumps(state.snapshot()).encode(), 'application/json')
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if self.path.startswith('/reset'):
                state.reset(self.path.endswith('capture'))
                self.reply(b'{}', 'application/json'); return
            if self.headers.get('Content-Encoding') == 'gzip': body = gzip.decompress(body)
            signal = self.path.rsplit('/',1)[-1]
            cls = metrics.ExportMetricsServiceRequest if signal == 'metrics' else traces.ExportTraceServiceRequest
            request = cls()
            if 'json' in self.headers.get('Content-Type', ''):
                from google.protobuf.json_format import Parse
                Parse(body, request)
            else: request.ParseFromString(body)
            state.accept(signal, request)
            self.reply(b'', 'application/x-protobuf')
    server = grpc.server(ThreadPoolExecutor(max_workers=4), options=[('grpc.max_receive_message_length', 16*1024*1024)])
    mg.add_MetricsServiceServicer_to_server(Metrics(), server)
    tg.add_TraceServiceServicer_to_server(Traces(), server)
    server.add_insecure_port('127.0.0.1:14317'); server.start()
    ThreadingHTTPServer(('127.0.0.1', 14318), HTTP).serve_forever()


if __name__ == '__main__': serve()
