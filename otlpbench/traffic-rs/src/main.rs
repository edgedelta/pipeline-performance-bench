use bytes::{BufMut, Bytes, BytesMut};
use clap::{Parser, Subcommand};
use http_body_util::{BodyExt, Full};
use hyper::{body::Incoming, service::service_fn, Request, Response};
use hyper_util::rt::TokioIo;
use opentelemetry_proto::tonic::{
    collector::metrics::v1::{
        metrics_service_server::{MetricsService, MetricsServiceServer},
        ExportMetricsServiceRequest, ExportMetricsServiceResponse,
    },
    metrics::v1::{metric::Data, number_data_point::Value},
};
use prost::Message;
use serde::Serialize;
use std::{
    convert::Infallible,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    net::TcpListener,
    sync::mpsc,
    task::JoinSet,
    time::{sleep_until, Instant},
};
use tonic::{
    codec::{Codec, DecodeBuf, Decoder, EncodeBuf, Encoder},
    transport::{Channel, Endpoint, Server},
    Status,
};

type Error = Box<dyn std::error::Error + Send + Sync>;

#[derive(Parser)]
struct Args {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Sink {
        #[arg(long, default_value = "127.0.0.1:14317")]
        grpc_addr: String,
        #[arg(long, default_value = "127.0.0.1:14318")]
        http_addr: String,
    },
    Load {
        #[arg(long)]
        fixture: String,
        #[arg(long, default_value = "http://127.0.0.1:4317")]
        endpoint: String,
        #[arg(long, default_value_t = 10000)]
        rps: u64,
        #[arg(long, default_value_t = 32)]
        connections: usize,
        #[arg(long, default_value_t = 512)]
        concurrency: usize,
        #[arg(long, default_value_t = 60)]
        seconds: u64,
        #[arg(long, default_value_t = 5)]
        timeout_seconds: u64,
        #[arg(long, default_value_t = 0)]
        sequence_offset: u64,
    },
}

#[derive(Default, Clone, Serialize)]
struct Counts {
    requests: u64,
    points: u64,
    value_sum: f64,
    bytes: u64,
}
fn count(req: &ExportMetricsServiceRequest) -> Counts {
    let mut c = Counts {
        requests: 1,
        ..Counts::default()
    };
    for r in &req.resource_metrics {
        for s in &r.scope_metrics {
            for m in &s.metrics {
                match &m.data {
                    Some(Data::Sum(v)) => {
                        c.points += v.data_points.len() as u64;
                        for p in &v.data_points {
                            c.value_sum += match p.value {
                                Some(Value::AsInt(n)) => n as f64,
                                Some(Value::AsDouble(n)) => n,
                                None => 0.0,
                            };
                        }
                    }
                    Some(Data::Gauge(v)) => {
                        c.points += v.data_points.len() as u64;
                        for p in &v.data_points {
                            c.value_sum += match p.value {
                                Some(Value::AsInt(n)) => n as f64,
                                Some(Value::AsDouble(n)) => n,
                                None => 0.0,
                            };
                        }
                    }
                    Some(Data::Histogram(v)) => c.points += v.data_points.len() as u64,
                    Some(Data::ExponentialHistogram(v)) => c.points += v.data_points.len() as u64,
                    Some(Data::Summary(v)) => c.points += v.data_points.len() as u64,
                    None => {}
                }
            }
        }
    }
    c
}
#[derive(Clone, Default)]
struct Sink {
    totals: Arc<Mutex<Counts>>,
}
impl Sink {
    fn accept(&self, req: &ExportMetricsServiceRequest, bytes: usize) -> Result<(), &'static str> {
        let c = count(req);
        let mut t = self.totals.lock().map_err(|_| "counter lock poisoned")?;
        t.requests += 1;
        t.points += c.points;
        t.value_sum += c.value_sum;
        t.bytes += bytes as u64;
        Ok(())
    }
    async fn http(&self, req: Request<Incoming>) -> Result<Response<Full<Bytes>>, Infallible> {
        let path = req.uri().path().to_owned();
        let method = req.method().clone();
        let result: Result<Vec<u8>, Error> = async {
            if path == "/stats" && method == hyper::Method::GET {
                return Ok(serde_json::to_vec(
                    &*self.totals.lock().map_err(|_| "counter lock poisoned")?,
                )?);
            }
            if path == "/reset" && method == hyper::Method::POST {
                *self.totals.lock().map_err(|_| "counter lock poisoned")? = Counts::default();
                return Ok(Vec::new());
            }
            if path != "/v1/metrics" || method != hyper::Method::POST {
                return Err("unsupported endpoint".into());
            }
            if req.headers().get("content-encoding").is_some() {
                return Err(
                    "compressed requests are not supported by this uncompressed benchmark".into(),
                );
            }
            let body = http_body_util::Limited::new(req.into_body(), 64 << 20)
                .collect()
                .await?
                .to_bytes();
            let decoded = ExportMetricsServiceRequest::decode(body.clone())?;
            self.accept(&decoded, body.len())?;
            Ok(Vec::new())
        }
        .await;
        let (status, body) = match result {
            Ok(b) => (200, b),
            Err(e) => (400, e.to_string().into_bytes()),
        };
        let mut response = Response::new(Full::new(Bytes::from(body)));
        *response.status_mut() = hyper::StatusCode::from_u16(status).expect("valid status");
        response.headers_mut().insert(
            hyper::header::CONTENT_TYPE,
            hyper::header::HeaderValue::from_static(if path == "/stats" {
                "application/json"
            } else {
                "application/x-protobuf"
            }),
        );
        Ok(response)
    }
}
#[tonic::async_trait]
impl MetricsService for Sink {
    async fn export(
        &self,
        req: tonic::Request<ExportMetricsServiceRequest>,
    ) -> Result<tonic::Response<ExportMetricsServiceResponse>, Status> {
        let req = req.into_inner();
        self.accept(&req, req.encoded_len())
            .map_err(Status::internal)?;
        Ok(tonic::Response::new(ExportMetricsServiceResponse {
            partial_success: None,
        }))
    }
}
async fn serve(grpc_addr: String, http_addr: String) -> Result<(), Error> {
    let sink = Sink::default();
    let listener = TcpListener::bind(http_addr).await?;
    let grpc = Server::builder()
        .initial_stream_window_size(8 << 20)
        .initial_connection_window_size(32 << 20)
        .add_service(MetricsServiceServer::new(sink.clone()).max_decoding_message_size(64 << 20))
        .serve(grpc_addr.parse()?);
    let http = async move {
        loop {
            let (stream, _) = listener.accept().await?;
            stream.set_nodelay(true)?;
            let s = sink.clone();
            tokio::spawn(async move {
                let svc = service_fn(move |req| {
                    let s = s.clone();
                    async move { s.http(req).await }
                });
                if let Err(e) = hyper::server::conn::http1::Builder::new()
                    .serve_connection(TokioIo::new(stream), svc)
                    .await
                {
                    eprintln!("HTTP connection: {e}");
                }
            });
        }
        #[allow(unreachable_code)]
        Ok::<(), Error>(())
    };
    tokio::select! {r=grpc=>r.map_err(Into::into),r=http=>r}
}

// Encode prepared protobuf bytes without allocating a point object per request.
#[derive(Default)]
struct RawCodec;
struct RawEncoder;
struct ResponseDecoder;
impl Codec for RawCodec {
    type Encode = Bytes;
    type Decode = ExportMetricsServiceResponse;
    type Encoder = RawEncoder;
    type Decoder = ResponseDecoder;
    fn encoder(&mut self) -> RawEncoder {
        RawEncoder
    }
    fn decoder(&mut self) -> ResponseDecoder {
        ResponseDecoder
    }
}
impl Encoder for RawEncoder {
    type Item = Bytes;
    type Error = Status;
    fn encode(&mut self, item: Bytes, dst: &mut EncodeBuf<'_>) -> Result<(), Status> {
        dst.put(item);
        Ok(())
    }
}
impl Decoder for ResponseDecoder {
    type Item = ExportMetricsServiceResponse;
    type Error = Status;
    fn decode(&mut self, src: &mut DecodeBuf<'_>) -> Result<Option<Self::Item>, Status> {
        ExportMetricsServiceResponse::decode(src)
            .map(Some)
            .map_err(|e| Status::internal(e.to_string()))
    }
}
const BOUNDS_US: [u64; 11] = [
    1000, 2000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000, 5000000,
];
#[derive(Default, Serialize)]
struct WorkerStats {
    started: u64,
    completed: u64,
    completed_in_window: u64,
    accepted_points: u64,
    rejected_points: u64,
    rpc_errors: u64,
    error_examples: Vec<String>,
    expired: u64,
    latency_buckets: [u64; 12],
}
#[derive(Serialize)]
struct ResultData {
    target_rps: u64,
    batch: u64,
    connections: usize,
    concurrency: usize,
    seconds: u64,
    scheduled_requests: u64,
    missed_requests: u64,
    achieved_rps: f64,
    drain_seconds: f64,
    input_bytes_per_request: usize,
    latency_bounds_us: [u64; 11],
    #[serde(flatten)]
    stats: WorkerStats,
}
fn patch_request(template: &[u8], offset: usize, seq: u64) -> Bytes {
    let mut b = BytesMut::from(template);
    let mut n = seq;
    for i in (offset..offset + 20).rev() {
        b[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    b.freeze()
}
struct LoadConfig {
    fixture: String,
    endpoint: String,
    rps: u64,
    connections: usize,
    concurrency: usize,
    seconds: u64,
    timeout_seconds: u64,
    sequence_offset: u64,
}
async fn load(c: LoadConfig) -> Result<ResultData, Error> {
    if c.rps == 0
        || c.connections == 0
        || c.concurrency == 0
        || c.seconds == 0
        || c.timeout_seconds == 0
    {
        return Err("all load parameters must be positive".into());
    }
    let template = Bytes::from(tokio::fs::read(c.fixture).await?);
    let decoded = ExportMetricsServiceRequest::decode(template.clone())?;
    let batch = count(&decoded).points;
    if batch == 0 {
        return Err("fixture must contain metric points".into());
    }
    let marker = b"00000000000000000000";
    let offsets: Vec<_> = template
        .windows(marker.len())
        .enumerate()
        .filter_map(|(i, v)| (v == marker).then_some(i))
        .collect();
    if offsets.len() != 1 {
        return Err("fixture must contain exactly one 20-zero bench.batch placeholder".into());
    }
    let offset = offsets[0];
    let mut channels: Vec<Channel> = Vec::new();
    for _ in 0..c.connections {
        channels.push(
            Endpoint::from_shared(c.endpoint.clone())?
                .initial_stream_window_size(8 << 20)
                .initial_connection_window_size(32 << 20)
                .tcp_nodelay(true)
                .connect_timeout(Duration::from_secs(10))
                .connect()
                .await?,
        )
    }
    let start = Instant::now() + Duration::from_millis(100);
    let end = start + Duration::from_secs(c.seconds);
    let mut workers = JoinSet::new();
    let mut senders = Vec::new();
    for i in 0..c.concurrency {
        let (tx, mut rx) = mpsc::channel::<u64>(1);
        senders.push(tx);
        let channel = channels[i % c.connections].clone();
        let template = template.clone();
        let timeout = Duration::from_secs(c.timeout_seconds);
        workers.spawn(async move {
            let mut stats = WorkerStats::default();
            let mut client = tonic::client::Grpc::new(channel);
            while let Some(seq) = rx.recv().await {
                if Instant::now() >= end {
                    stats.expired += 1;
                    continue;
                }
                stats.started += 1;
                let t = Instant::now();
                let response = tokio::time::timeout(timeout, async {
                    client
                        .ready()
                        .await
                        .map_err(|e| Status::unavailable(e.to_string()))?;
                    client
                        .unary(
                            tonic::Request::new(patch_request(&template, offset, seq)),
                            tonic::codegen::http::uri::PathAndQuery::from_static(
                                "/opentelemetry.proto.collector.metrics.v1.MetricsService/Export",
                            ),
                            RawCodec,
                        )
                        .await
                })
                .await;
                let us = t.elapsed().as_micros() as u64;
                let bucket = BOUNDS_US.iter().position(|v| us <= *v).unwrap_or(11);
                stats.latency_buckets[bucket] += 1;
                match response {
                    Ok(Ok(r)) => {
                        let rejected = r
                            .into_inner()
                            .partial_success
                            .map(|p| p.rejected_data_points)
                            .unwrap_or(0);
                        if rejected < 0 || rejected as u64 > batch {
                            stats.rpc_errors += 1;
                            continue;
                        }
                        stats.completed += 1;
                        if Instant::now() < end {
                            stats.completed_in_window += 1
                        }
                        stats.rejected_points += rejected as u64;
                        stats.accepted_points += batch - rejected as u64;
                    }
                    other => {
                        stats.rpc_errors += 1;
                        if stats.error_examples.len() < 3 {
                            stats.error_examples.push(match other {
                                Ok(Err(e)) => e.to_string(),
                                Err(e) => e.to_string(),
                                _ => unreachable!(),
                            });
                        }
                    }
                }
            }
            stats
        });
    }
    let total = c
        .rps
        .checked_mul(c.seconds)
        .ok_or("request count overflow")?;
    c.sequence_offset
        .checked_add(total)
        .ok_or("sequence overflow")?;
    let mut issued = 0u64;
    let mut missed = 0u64;
    for tick in 0..c.seconds * 1000 {
        let due = start + Duration::from_millis(tick);
        sleep_until(due).await;
        let limit = ((tick + 1) as u128 * c.rps as u128 / 1000) as u64;
        if Instant::now().saturating_duration_since(due) > Duration::from_millis(5) {
            missed += limit - issued;
            issued = limit;
            continue;
        }
        while issued < limit {
            if senders[issued as usize % c.concurrency]
                .try_send(c.sequence_offset + issued)
                .is_err()
            {
                missed += 1
            }
            issued += 1;
        }
    }
    drop(senders);
    let mut stats = WorkerStats::default();
    while let Some(s) = workers.join_next().await {
        let s = s?;
        stats.started += s.started;
        stats.completed += s.completed;
        stats.completed_in_window += s.completed_in_window;
        stats.accepted_points += s.accepted_points;
        stats.rejected_points += s.rejected_points;
        stats.rpc_errors += s.rpc_errors;
        stats.expired += s.expired;
        for e in s.error_examples {
            if stats.error_examples.len() < 3 && !stats.error_examples.contains(&e) {
                stats.error_examples.push(e);
            }
        }
        for (a, b) in stats.latency_buckets.iter_mut().zip(s.latency_buckets) {
            *a += b
        }
    }
    sleep_until(end).await;
    Ok(ResultData {
        target_rps: c.rps,
        batch,
        connections: c.connections,
        concurrency: c.concurrency,
        seconds: c.seconds,
        scheduled_requests: total,
        missed_requests: missed + stats.expired,
        achieved_rps: stats.completed_in_window as f64 / c.seconds as f64,
        drain_seconds: Instant::now().saturating_duration_since(end).as_secs_f64(),
        input_bytes_per_request: template.len(),
        latency_bounds_us: BOUNDS_US,
        stats,
    })
}
#[tokio::main]
async fn main() -> Result<(), Error> {
    match Args::parse().command {
        Command::Sink {
            grpc_addr,
            http_addr,
        } => serve(grpc_addr, http_addr).await?,
        Command::Load {
            fixture,
            endpoint,
            rps,
            connections,
            concurrency,
            seconds,
            timeout_seconds,
            sequence_offset,
        } => {
            let r = load(LoadConfig {
                fixture,
                endpoint,
                rps,
                connections,
                concurrency,
                seconds,
                timeout_seconds,
                sequence_offset,
            })
            .await?;
            println!("{}", serde_json::to_string(&r)?);
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn counts_match_for_grouped_and_expanded_metrics() {
        use opentelemetry_proto::tonic::metrics::v1::{
            Metric, NumberDataPoint, ResourceMetrics, ScopeMetrics, Sum,
        };
        let points: Vec<_> = [1, 2]
            .into_iter()
            .map(|n| NumberDataPoint {
                value: Some(Value::AsInt(n)),
                ..Default::default()
            })
            .collect();
        let metric = |points| Metric {
            name: "bench.requests".into(),
            data: Some(Data::Sum(Sum {
                data_points: points,
                ..Default::default()
            })),
            ..Default::default()
        };
        let request = |metrics| ExportMetricsServiceRequest {
            resource_metrics: vec![ResourceMetrics {
                scope_metrics: vec![ScopeMetrics {
                    metrics,
                    ..Default::default()
                }],
                ..Default::default()
            }],
        };
        let grouped = request(vec![metric(points.clone())]);
        let expanded = request(points.into_iter().map(|p| metric(vec![p])).collect());
        for r in [grouped, expanded] {
            let c = count(&r);
            assert_eq!(c.points, 2);
            assert_eq!(c.value_sum, 3.0);
        }
    }

    #[test]
    fn sequence_patch_preserves_protobuf() {
        use opentelemetry_proto::tonic::{
            common::v1::{any_value, AnyValue, KeyValue},
            metrics::v1::ResourceMetrics,
            resource::v1::Resource,
        };
        let r = ExportMetricsServiceRequest {
            resource_metrics: vec![ResourceMetrics {
                resource: Some(Resource {
                    attributes: vec![KeyValue {
                        key: "bench.batch".into(),
                        value: Some(AnyValue {
                            value: Some(any_value::Value::StringValue(
                                "00000000000000000000".into(),
                            )),
                        }),
                    }],
                    ..Default::default()
                }),
                ..Default::default()
            }],
        };
        let b = r.encode_to_vec();
        let offset = b
            .windows(20)
            .position(|v| v == b"00000000000000000000")
            .unwrap();
        let p = patch_request(&b, offset, u64::MAX);
        let decoded = ExportMetricsServiceRequest::decode(p).unwrap();
        assert_eq!(
            decoded.resource_metrics[0]
                .resource
                .as_ref()
                .unwrap()
                .attributes[0]
                .value
                .as_ref()
                .unwrap()
                .value,
            Some(any_value::Value::StringValue(u64::MAX.to_string()))
        );
    }
}
