//! HTTP/1 fixed-rate counterpart of loadgen_extensions/fixed_rate.go.
//! Reporting compatibility does not imply a full replacement for legacy Go CLI modes.
use bytes::Bytes;
use clap::{Parser, ValueEnum};
use http_body_util::{BodyExt, Full};
use hyper::{Request, Uri};
use hyper_util::rt::TokioIo;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    error::Error,
    fs, io,
    pin::Pin,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering::Relaxed},
    },
    task::{Context, Poll},
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    net::TcpStream,
    sync::{Semaphore, watch},
    task::JoinSet,
};

type AnyError = Box<dyn Error + Send + Sync>;
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum DispatchMode {
    Workers,
    Tasks,
}

#[derive(Parser, Debug, Clone)]
#[command(
    version,
    about = "Fixed-rate HTTP ingestion load generator; plain HTTP/1 only"
)]
struct Args {
    #[arg(long, default_value = "http://127.0.0.1:8080/ingest")]
    endpoint: String,
    #[arg(long)]
    fixed_rate: u64,
    #[arg(long, default_value_t = 256)]
    workers: usize,
    #[arg(long, value_enum, default_value_t = DispatchMode::Workers)]
    dispatch_mode: DispatchMode,
    /// Active HTTP requests, independent of Tokio runtime thread count.
    #[arg(long, default_value_t = 256)]
    max_inflight: usize,
    /// Additional bounded waiting tasks; zero disables pending buffering.
    #[arg(long, default_value_t = 256)]
    pending_capacity: usize,
    #[arg(long, default_value_t = 1)]
    number: usize,
    #[arg(long, default_value="30s", value_parser=duration)]
    timeout: Duration,
    #[arg(long, default_value="60s", value_parser=duration)]
    total_time: Duration,
    #[arg(long, default_value="10s", value_parser=duration)]
    fixed_warmup: Duration,
    #[arg(long)]
    fixed_payload_file: String,
    #[arg(long)]
    fixed_output: String,
    #[arg(long, default_value = "")]
    fixed_cgroup: String,
    #[arg(long, default_value_t = 2)]
    max_retries: u32,
    #[arg(long, default_value="false", num_args=0..=1, default_missing_value="true")]
    retry_ambiguous: bool,
    #[arg(long)]
    fixed_calibration: bool,
    #[arg(long)]
    runtime_threads: Option<usize>,
}
fn duration(s: &str) -> Result<Duration, String> {
    let (n, scale) = if let Some(x) = s.strip_suffix("ms") {
        (x, 0.001)
    } else if let Some(x) = s.strip_suffix('s') {
        (x, 1.0)
    } else if let Some(x) = s.strip_suffix('m') {
        (x, 60.0)
    } else {
        return Err("use ms, s or m".into());
    };
    let n: f64 = n.parse().map_err(|_| "invalid duration")?;
    if !n.is_finite() || n < 0.0 || n * scale > 86400.0 {
        return Err("duration out of range".into());
    }
    Ok(Duration::from_secs_f64(n * scale))
}
fn due(rate: u64, elapsed: Duration, duration: Duration, accounted: u64) -> (u64, u64) {
    let total = (rate as u128 * elapsed.min(duration).as_nanos() / 1_000_000_000) as u64;
    let pending = total.saturating_sub(accounted);
    let burst = rate.div_ceil(200).max(1); // 5 ms, exactly the Go catch-up allowance.
    (pending.min(burst), pending.saturating_sub(burst))
}
fn read_num(path: &str) -> Option<u64> {
    fs::read_to_string(path).ok()?.trim().parse().ok()
}
fn sample(cgroup: &str, elapsed: f64) -> Value {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::zeroed();
    // getrusage writes the provided valid rusage buffer on success.
    let cpu = unsafe {
        if libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) == 0 {
            let u = usage.assume_init();
            Some(
                (u.ru_utime.tv_sec + u.ru_stime.tv_sec) as u64 * 1_000_000
                    + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) as u64,
            )
        } else {
            None
        }
    };
    let rss = fs::read_to_string("/proc/self/statm")
        .ok()
        .and_then(|s| s.split_whitespace().nth(1)?.parse::<u64>().ok())
        .map(|n| n * unsafe { libc::sysconf(libc::_SC_PAGESIZE) } as u64);
    let agent_cpu = fs::read_to_string(format!("{cgroup}/cpu.stat"))
        .ok()
        .and_then(|s| {
            s.lines()
                .find_map(|l| l.strip_prefix("usage_usec ")?.parse::<u64>().ok())
        });
    let agent_mem = if cgroup.is_empty() {
        None
    } else {
        read_num(&format!("{cgroup}/memory.current"))
    };
    let host = fs::read_to_string("/proc/stat")
        .ok()
        .and_then(|s| s.lines().next().map(str::to_owned))
        .and_then(|s| {
            s.split_whitespace()
                .skip(1)
                .take(8)
                .map(str::parse::<u64>)
                .collect::<Result<Vec<_>, _>>()
                .ok()
        })
        .filter(|v| v.len() == 8)
        .map(|v| {
            let total: u64 = v.iter().sum();
            (total, total - v[3] - v[4])
        });
    json!({"elapsed_seconds":elapsed,"agent_cpu_usage_usec":agent_cpu,"agent_memory_bytes":agent_mem,"generator_cpu_usage_usec":cpu,"generator_rss_bytes":rss,"host_total_ticks":host.map(|h|h.0),"host_busy_ticks":host.map(|h|h.1)})
}

/// Observe successful socket writes, not merely request construction or responses.
/// One request at a time per connection. Retries share the logical offered marker.
struct Marker {
    offered: AtomicBool,
    deadline: Instant,
}
struct WriteState {
    header_tail: u32,
    header_done: bool,
    remaining: usize,
    wrote: bool,
    marker: Arc<Marker>,
}
impl WriteState {
    fn new(body: usize, marker: Arc<Marker>) -> Self {
        Self {
            header_tail: 0,
            header_done: false,
            remaining: body,
            wrote: false,
            marker,
        }
    }
    fn observe(&mut self, bytes: &[u8]) {
        self.wrote |= !bytes.is_empty();
        let mut pos = 0;
        if !self.header_done {
            for &b in bytes {
                self.header_tail = (self.header_tail << 8) | b as u32;
                pos += 1;
                if self.header_tail == 0x0d0a0d0a {
                    self.header_done = true;
                    break;
                }
            }
        }
        if self.header_done {
            self.remaining = self.remaining.saturating_sub(bytes.len() - pos);
            if self.remaining == 0 && Instant::now() < self.marker.deadline {
                self.marker.offered.store(true, Relaxed)
            }
        }
    }
}
struct Observed {
    stream: TcpStream,
    state: Arc<Mutex<WriteState>>,
}
impl AsyncRead for Observed {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.stream).poll_read(cx, buf)
    }
}
impl AsyncWrite for Observed {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        let result = Pin::new(&mut self.stream).poll_write(cx, buf);
        if let Poll::Ready(Ok(n)) = result {
            self.state.lock().unwrap().observe(&buf[..n])
        }
        result
    }
    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.stream).poll_flush(cx)
    }
    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.stream).poll_shutdown(cx)
    }
    fn is_write_vectored(&self) -> bool {
        true
    }
    fn poll_write_vectored(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bufs: &[io::IoSlice<'_>],
    ) -> Poll<io::Result<usize>> {
        let result = Pin::new(&mut self.stream).poll_write_vectored(cx, bufs);
        if let Poll::Ready(Ok(mut n)) = result {
            let mut state = self.state.lock().unwrap();
            for b in bufs {
                let take = n.min(b.len());
                state.observe(&b[..take]);
                n -= take;
                if n == 0 {
                    break;
                }
            }
        }
        result
    }
}
struct Connection {
    sender: hyper::client::conn::http1::SendRequest<Full<Bytes>>,
    state: Arc<Mutex<WriteState>>,
    driver: tokio::task::JoinHandle<()>,
}
impl Drop for Connection {
    fn drop(&mut self) {
        self.driver.abort();
    }
}
async fn connect(
    host: &str,
    port: u16,
    body: usize,
    marker: Arc<Marker>,
) -> Result<Connection, AnyError> {
    let stream = TcpStream::connect((host, port)).await?;
    stream.set_nodelay(true)?;
    let state = Arc::new(Mutex::new(WriteState::new(body, marker)));
    let (sender, connection) = hyper::client::conn::http1::handshake(TokioIo::new(Observed {
        stream,
        state: state.clone(),
    }))
    .await?;
    let driver = tokio::spawn(async move {
        let _ = connection.await;
    });
    Ok(Connection {
        sender,
        state,
        driver,
    })
}
fn connection_failure(mut error: &(dyn Error + 'static)) -> bool {
    loop {
        if let Some(e) = error.downcast_ref::<io::Error>()
            && matches!(
                e.kind(),
                io::ErrorKind::UnexpectedEof
                    | io::ErrorKind::ConnectionReset
                    | io::ErrorKind::ConnectionAborted
                    | io::ErrorKind::ConnectionRefused
                    | io::ErrorKind::BrokenPipe
                    | io::ErrorKind::NotConnected
            )
        {
            return true;
        }
        if let Some(e) = error.downcast_ref::<hyper::Error>()
            && (e.is_incomplete_message() || e.is_closed())
        {
            return true;
        }
        match error.source() {
            Some(e) => error = e,
            None => return false,
        }
    }
}
fn retryable_request_error(error: &(dyn Error + 'static), head: bool, wrote: bool) -> bool {
    let unsent_closed = !wrote
        && error
            .downcast_ref::<hyper::Error>()
            .is_some_and(|e| e.is_canceled());
    !head && (connection_failure(error) || unsent_closed)
}

#[derive(Default, Serialize)]
struct Counters {
    dispatched_logs: u64,
    offered_logs: u64,
    acknowledged_logs: u64,
    acknowledged_after_window: u64,
    errors: u64,
    backpressure: u64,
    connection_errors: u64,
    retry_attempts: u64,
    recovered_requests: u64,
    ambiguous_deliveries: u64,
    expired_before_dispatch_logs: u64,
    http_status_counts: BTreeMap<u16, u64>,
    error_samples: Vec<String>,
    final_error_samples: Vec<String>,
    #[serde(skip)]
    latency_ns: u128,
}
impl Counters {
    fn final_diagnostic(&mut self, message: String) {
        if self.final_error_samples.len() < 8 {
            self.final_error_samples.push(message);
        }
    }
    fn diagnostic(&mut self, message: String) {
        // No URLs, payloads, headers or credentials; bound retained diagnostics.
        if self.error_samples.len() < 8 {
            self.error_samples.push(message);
        }
    }
    fn add(&mut self, o: Self) {
        macro_rules! add {($($f:ident),*)=>{$(self.$f+=o.$f;)*}}
        add!(
            dispatched_logs,
            offered_logs,
            acknowledged_logs,
            acknowledged_after_window,
            errors,
            backpressure,
            connection_errors,
            retry_attempts,
            recovered_requests,
            ambiguous_deliveries,
            expired_before_dispatch_logs,
            latency_ns
        );
        for message in o.final_error_samples {
            self.final_diagnostic(message);
        }
        for message in o.error_samples {
            self.diagnostic(message);
        }
        for (k, n) in o.http_status_counts {
            *self.http_status_counts.entry(k).or_default() += n;
        }
    }
}
async fn attempt(
    conn: &mut Option<Connection>,
    uri: &Uri,
    payload: Bytes,
    marker: Arc<Marker>,
    fresh: bool,
    head_received: &mut bool,
    status: &mut Option<u16>,
) -> Result<(), AnyError> {
    if fresh || conn.as_ref().is_some_and(|c| c.sender.is_closed()) {
        *conn = None
    }
    if conn.is_none() {
        *conn = Some(
            connect(
                uri.host().unwrap(),
                uri.port_u16().unwrap_or(80),
                payload.len(),
                marker.clone(),
            )
            .await?,
        )
    }
    let c = conn.as_mut().unwrap();
    *c.state.lock().unwrap() = WriteState::new(payload.len(), marker);
    c.sender.ready().await?;
    let mut builder = Request::post(uri.path_and_query().map(|p| p.as_str()).unwrap_or("/"))
        .header("Host", uri.authority().unwrap().as_str())
        .header("Content-Type", "application/json")
        .header("User-Agent", "pipeline-loadgen-rust/0.1")
        .header("Content-Length", payload.len());
    if fresh {
        builder = builder.header("Connection", "close")
    }
    let response = c
        .sender
        .send_request(builder.body(Full::new(payload))?)
        .await?;
    *head_received = true;
    *status = Some(response.status().as_u16());
    let mut body = response.into_body();
    while let Some(frame) = body.frame().await {
        let _ = frame?;
    }
    Ok(())
}
#[derive(Default)]
struct Progress {
    dispatched: AtomicU64,
    completed: AtomicU64,
}
struct Workload {
    args: Arc<Args>,
    uri: Uri,
    payloads: Arc<Vec<Bytes>>,
    deadline: Instant,
    progress: Arc<Progress>,
}
async fn send_one(
    work: &Workload,
    index: u64,
    conn: &mut Option<Connection>,
    stats: &mut Counters,
    cancel: &mut watch::Receiver<bool>,
) {
    let args = &work.args;
    let uri = &work.uri;
    let deadline = work.deadline;
    let progress = &work.progress;
    if Instant::now() >= deadline || *cancel.borrow() {
        stats.expired_before_dispatch_logs += 1;
        return;
    }
    stats.dispatched_logs += 1;
    progress.dispatched.fetch_add(1, Relaxed);
    let sent = Instant::now();
    let marker = Arc::new(Marker {
        offered: AtomicBool::new(false),
        deadline,
    });
    let mut ambiguous = false;
    let mut head = false;
    let mut status = None;
    let operation = async {
        for retry in 0..=args.max_retries {
            if retry > 0 {
                stats.retry_attempts += 1;
            }
            let result = attempt(
                conn,
                uri,
                work.payloads[index as usize % work.payloads.len()].clone(),
                marker.clone(),
                retry > 0,
                &mut head,
                &mut status,
            )
            .await;
            if result.is_ok() {
                return Some(retry);
            }
            let wrote = conn.as_ref().is_some_and(|c| c.state.lock().unwrap().wrote);
            let error = result.as_ref().unwrap_err().as_ref();
            // Hyper can cancel dispatch when a reused connection closes before
            // serialization. This is safe to replay only if no bytes were written.
            // Application cancellation and request timeout bypass this branch.
            let is_connection = retryable_request_error(error, head, wrote);
            stats.diagnostic(format!(
                "attempt={} head={} wrote={} retryable={} error={error:?}",
                retry + 1,
                head,
                wrote,
                is_connection
            ));
            *conn = None;
            if is_connection {
                stats.connection_errors += 1;
                if wrote && !ambiguous {
                    stats.ambiguous_deliveries += 1;
                    ambiguous = true;
                }
            }
            if !is_connection || retry == args.max_retries || (wrote && !args.retry_ambiguous) {
                stats.final_diagnostic(format!(
                    "attempt={} head={} wrote={} retryable={} error={error:?}",
                    retry + 1,
                    head,
                    wrote,
                    is_connection
                ));
                return None;
            }
            tokio::time::sleep(Duration::from_millis((retry as u64 + 1) * 10)).await;
        }
        None
    };
    let outcome = tokio::select! {biased;
        _=cancel.changed()=>Err("application canceled"),
        r=tokio::time::timeout(args.timeout,operation)=>r.map_err(|_| "request timeout")
    };
    if let Err(reason) = outcome {
        stats.final_diagnostic(reason.to_owned());
    }
    let recovered = outcome.ok().flatten();
    stats.offered_logs += u64::from(marker.offered.load(Relaxed));
    if let Some(code) = status {
        *stats.http_status_counts.entry(code).or_default() += 1;
    }
    match recovered {
        Some(retries) if status.is_some_and(|s| s < 400) => {
            if Instant::now() < deadline {
                stats.acknowledged_logs += 1
            } else {
                stats.acknowledged_after_window += 1
            }
            if retries > 0 {
                stats.recovered_requests += 1;
                *conn = None;
            }
        }
        _ => {
            stats.errors += 1;
            if recovered.is_some() {
                stats.final_diagnostic(format!("HTTP status {}", status.unwrap_or(0)));
            }
            if recovered.is_some() && matches!(status, Some(429 | 503)) {
                stats.backpressure += 1;
            }
            // A fully read HTTP rejection can reuse its keep-alive connection,
            // just as Go does. Broken bodies and fresh retry connections cannot.
            if recovered != Some(0) {
                *conn = None;
            }
        }
    }
    stats.latency_ns += sent.elapsed().as_nanos();
    progress.completed.fetch_add(1, Relaxed);
}
async fn worker(
    args: Arc<Args>,
    uri: Uri,
    payloads: Arc<Vec<Bytes>>,
    queue: async_channel::Receiver<u64>,
    deadline: Instant,
    progress: Arc<Progress>,
    mut cancel: watch::Receiver<bool>,
) -> Counters {
    let work = Workload {
        args,
        uri,
        payloads,
        deadline,
        progress,
    };
    let mut stats = Counters::default();
    let mut conn = None;
    while let Ok(index) = queue.recv().await {
        send_one(&work, index, &mut conn, &mut stats, &mut cancel).await;
    }
    stats
}
async fn phase(
    args: Arc<Args>,
    payloads: Arc<Vec<Bytes>>,
    duration: Duration,
    mut cancel: watch::Receiver<bool>,
) -> Result<Value, AnyError> {
    let start = Instant::now();
    let deadline = start + duration;
    let (tx, rx) = async_channel::bounded(args.workers);
    let progress = Arc::new(Progress::default());
    let uri: Uri = args.endpoint.parse()?;
    let mut tasks = Vec::new();
    for _ in 0..args.workers {
        tasks.push(tokio::spawn(worker(
            args.clone(),
            uri.clone(),
            payloads.clone(),
            rx.clone(),
            deadline,
            progress.clone(),
            cancel.clone(),
        )))
    }
    let mut samples = vec![sample(&args.fixed_cgroup, 0.0)];
    let mut tick = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_millis(1),
        Duration::from_millis(1),
    );
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut sample_tick = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_secs(1),
        Duration::from_secs(1),
    );
    let mut accounted = 0;
    let mut missed = 0;
    let mut dropped = 0;
    let mut canceled = *cancel.borrow();
    while !canceled {
        tokio::select! {biased;
            _=cancel.changed()=>{canceled=true;},
            _=tokio::time::sleep_until(deadline.into())=>break,
            _=sample_tick.tick()=>samples.push(sample(&args.fixed_cgroup,start.elapsed().as_secs_f64())),
            _=tick.tick()=>{let (due,late)=due(args.fixed_rate,start.elapsed(),duration,accounted);missed+=late;accounted+=late;for _ in 0..due {if tx.try_send(accounted).is_err(){dropped+=1;}accounted+=1;}}
        }
    }
    let elapsed = start.elapsed().as_secs_f64();
    samples.push(sample(&args.fixed_cgroup, elapsed));
    let scheduled = (args.fixed_rate as u128 * duration.as_nanos() / 1_000_000_000) as u64;
    missed += scheduled.saturating_sub(accounted);
    let inflight = progress
        .dispatched
        .load(Relaxed)
        .saturating_sub(progress.completed.load(Relaxed));
    let queued = tx.len();
    tx.close();
    let drain = Instant::now();
    let mut stats = Counters::default();
    for task in tasks {
        stats.add(task.await?);
    }
    let latency = if stats.dispatched_logs > 0 {
        stats.latency_ns as f64 / stats.dispatched_logs as f64 / 1e6
    } else {
        0.0
    };
    let mut result = serde_json::to_value(&stats)?;
    let obj = result.as_object_mut().unwrap();
    for (k,v) in json!({"duration_seconds":elapsed,"scheduled_logs":scheduled,"scheduler_missed_logs":missed,"worker_queue_dropped_logs":dropped,"client_inflight_at_end":inflight,"client_inflight_after_drain":progress.dispatched.load(Relaxed).saturating_sub(progress.completed.load(Relaxed)),"client_queue_at_end":queued,"http_drain_seconds":drain.elapsed().as_secs_f64(),"mean_response_latency_ms":latency,"resource_samples":samples,"canceled":canceled}).as_object().unwrap(){obj.insert(k.clone(),v.clone());}
    Ok(result)
}
/// Tasks never hold the pool mutex across network I/O. The HTTP semaphore limits
/// checked-out connections; the admission semaphore bounds active + waiting tasks.
struct TaskDispatcher {
    work: Arc<Workload>,
    http_slots: Arc<Semaphore>,
    admission: Arc<Semaphore>,
    idle: Arc<Mutex<Vec<Connection>>>,
    tasks: JoinSet<Counters>,
    peak_admitted: usize,
    waiting: Arc<AtomicU64>,
}
impl TaskDispatcher {
    fn new(work: Arc<Workload>) -> Self {
        Self {
            http_slots: Arc::new(Semaphore::new(work.args.max_inflight)),
            admission: Arc::new(Semaphore::new(
                work.args.max_inflight + work.args.pending_capacity,
            )),
            work,
            idle: Arc::new(Mutex::new(Vec::new())),
            tasks: JoinSet::new(),
            peak_admitted: 0,
            waiting: Arc::new(AtomicU64::new(0)),
        }
    }
    fn reap(&mut self, stats: &mut Counters) -> Result<(), AnyError> {
        while let Some(result) = self.tasks.try_join_next() {
            stats.add(result?);
        }
        Ok(())
    }
    fn schedule(&mut self, index: u64, mut cancel: watch::Receiver<bool>) -> bool {
        let Ok(admission) = self.admission.clone().try_acquire_owned() else {
            return false;
        };
        let capacity = self.work.args.max_inflight + self.work.args.pending_capacity;
        self.peak_admitted = self
            .peak_admitted
            .max(capacity - self.admission.available_permits());
        let slots = self.http_slots.clone();
        let pool = self.idle.clone();
        let work = self.work.clone();
        let waiting = self.waiting.clone();
        waiting.fetch_add(1, Relaxed);
        self.tasks.spawn(async move {
            let _admission = admission;
            let mut stats = Counters::default();
            let permit = tokio::select! { biased;
                _ = cancel.changed() => None,
                _ = tokio::time::sleep_until(work.deadline.into()) => None,
                p = slots.acquire_owned() => p.ok(),
            };
            waiting.fetch_sub(1, Relaxed);
            let Some(_permit) = permit else {
                stats.expired_before_dispatch_logs += 1;
                return stats;
            };
            let mut conn = pool.lock().unwrap().pop();
            send_one(&work, index, &mut conn, &mut stats, &mut cancel).await;
            if let Some(conn) = conn.filter(|c| !c.sender.is_closed()) {
                pool.lock().unwrap().push(conn);
            }
            stats
        });
        true
    }
}
async fn task_phase(
    args: Arc<Args>,
    payloads: Arc<Vec<Bytes>>,
    duration: Duration,
    mut cancel: watch::Receiver<bool>,
) -> Result<Value, AnyError> {
    let start = Instant::now();
    let deadline = start + duration;
    let progress = Arc::new(Progress::default());
    let work = Arc::new(Workload {
        uri: args.endpoint.parse()?,
        args: args.clone(),
        payloads,
        deadline,
        progress: progress.clone(),
    });
    let mut dispatcher = TaskDispatcher::new(work);
    let mut samples = vec![sample(&args.fixed_cgroup, 0.0)];
    let mut tick = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_millis(1),
        Duration::from_millis(1),
    );
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut sample_tick = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_secs(1),
        Duration::from_secs(1),
    );
    let (mut accounted, mut missed, mut dropped) = (0, 0, 0);
    let mut stats = Counters::default();
    let mut canceled = *cancel.borrow();
    while !canceled {
        tokio::select! { biased;
            _ = cancel.changed() => { canceled = true; },
            _ = tokio::time::sleep_until(deadline.into()) => break,
            _ = sample_tick.tick() => samples.push(sample(&args.fixed_cgroup, start.elapsed().as_secs_f64())),
            _ = tick.tick() => {
                dispatcher.reap(&mut stats)?;
                let (due, late) = due(args.fixed_rate, start.elapsed(), duration, accounted);
                missed += late; accounted += late;
                for _ in 0..due {
                    if !dispatcher.schedule(accounted, cancel.clone()) { dropped += 1; }
                    accounted += 1;
                }
            }
        }
    }
    let elapsed = start.elapsed().as_secs_f64();
    samples.push(sample(&args.fixed_cgroup, elapsed));
    let scheduled = (args.fixed_rate as u128 * duration.as_nanos() / 1_000_000_000) as u64;
    missed += scheduled.saturating_sub(accounted);
    let inflight = progress
        .dispatched
        .load(Relaxed)
        .saturating_sub(progress.completed.load(Relaxed));
    let queued = dispatcher.waiting.load(Relaxed);
    let drain = Instant::now();
    while let Some(result) = dispatcher.tasks.join_next().await {
        stats.add(result?);
    }
    let latency = if stats.dispatched_logs > 0 {
        stats.latency_ns as f64 / stats.dispatched_logs as f64 / 1e6
    } else {
        0.0
    };
    let mut result = serde_json::to_value(&stats)?;
    let obj = result.as_object_mut().unwrap();
    // Legacy queue-drop field remains the compatible admission-drop counter.
    for (k,v) in json!({"duration_seconds":elapsed,"scheduled_logs":scheduled,"scheduler_missed_logs":missed,"worker_queue_dropped_logs":dropped,"admission_dropped_logs":dropped,"expired_before_dispatch_logs":stats.expired_before_dispatch_logs,"client_inflight_at_end":inflight,"client_inflight_after_drain":progress.dispatched.load(Relaxed).saturating_sub(progress.completed.load(Relaxed)),"client_queue_at_end":queued,"http_drain_seconds":drain.elapsed().as_secs_f64(),"mean_response_latency_ms":latency,"resource_samples":samples,"canceled":canceled,"peak_admitted_tasks":dispatcher.peak_admitted,"max_inflight":args.max_inflight,"pending_capacity":args.pending_capacity}).as_object().unwrap() { obj.insert(k.clone(),v.clone()); }
    Ok(result)
}
async fn selected_phase(
    args: Arc<Args>,
    payloads: Arc<Vec<Bytes>>,
    duration: Duration,
    cancel: watch::Receiver<bool>,
) -> Result<Value, AnyError> {
    match args.dispatch_mode {
        DispatchMode::Workers => phase(args, payloads, duration, cancel).await,
        DispatchMode::Tasks => task_phase(args, payloads, duration, cancel).await,
    }
}
async fn calibration_server() -> Result<(String, tokio::task::JoinHandle<()>), AnyError> {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let task = tokio::spawn(async move {
        while let Ok((stream, _)) = listener.accept().await {
            tokio::spawn(async move {
                let service =
                    hyper::service::service_fn(|request: Request<hyper::body::Incoming>| async {
                        let _ = request.into_body().collect().await?;
                        Ok::<_, hyper::Error>(hyper::Response::new(Full::new(Bytes::new())))
                    });
                let _ = hyper::server::conn::http1::Builder::new()
                    .serve_connection(TokioIo::new(stream), service)
                    .await;
            });
        }
    });
    Ok((format!("http://{address}"), task))
}
async fn run(mut args: Args) -> Result<(), AnyError> {
    if args.fixed_rate == 0
        || args.fixed_rate > 10_000_000
        || args.workers == 0
        || args.workers > 65536
        || args.max_inflight == 0
        || args.max_inflight > 65536
        || args.pending_capacity > 65536
        || args.number != 1
        || args.total_time.is_zero()
        || args.timeout.is_zero()
        || args.max_retries > 2
    {
        return Err(
            "invalid rate/workers/duration/timeout; number=1 and max-retries<=2 required".into(),
        );
    }
    let uri: Uri = args.endpoint.parse()?;
    if uri.scheme_str() != Some("http")
        || uri.host().is_none()
        || uri.authority().unwrap().as_str().contains('@')
    {
        return Err("only plain HTTP/1 endpoints without userinfo are supported".into());
    }
    let raw = fs::read(&args.fixed_payload_file)?;
    let text = std::str::from_utf8(&raw)?.trim();
    if text.is_empty() {
        return Err("empty corpus".into());
    }
    let payloads = Arc::new(
        text.split('\n')
            .map(|line| {
                let _: Value = serde_json::from_str(line)?;
                Ok(Bytes::from(format!("{line}\n")))
            })
            .collect::<Result<Vec<_>, serde_json::Error>>()?,
    );
    let server = if args.fixed_calibration {
        let (endpoint, server) = calibration_server().await?;
        args.endpoint = endpoint;
        Some(server)
    } else {
        None
    };
    let args = Arc::new(args);
    let (cancel_tx, cancel_rx) = watch::channel(false);
    tokio::spawn(async move {
        #[cfg(unix)]
        {
            let mut term =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).unwrap();
            tokio::select! {_=tokio::signal::ctrl_c()=>{},_=term.recv()=>{}}
        }
        #[cfg(not(unix))]
        {
            let _ = tokio::signal::ctrl_c().await;
        }
        let _ = cancel_tx.send(true);
    });
    let warmup = if args.fixed_warmup.is_zero() {
        json!({})
    } else {
        selected_phase(
            args.clone(),
            payloads.clone(),
            args.fixed_warmup,
            cancel_rx.clone(),
        )
        .await?
    };
    let measured = selected_phase(args.clone(), payloads, args.total_time, cancel_rx).await?;
    let output = json!({"schema_version":2,"generator":"rust","generator_version":env!("CARGO_PKG_VERSION"),"target_logs_per_second":args.fixed_rate,"workers":if args.dispatch_mode == DispatchMode::Workers {Some(args.workers)} else {None},"dispatch_mode":args.dispatch_mode,"max_inflight":if args.dispatch_mode == DispatchMode::Workers {args.workers} else {args.max_inflight},"pending_capacity":if args.dispatch_mode == DispatchMode::Workers {args.workers} else {args.pending_capacity},"payload_sha256":format!("{:x}",Sha256::digest(&raw)),"warmup_seconds":args.fixed_warmup.as_secs_f64(),"configured_measurement_seconds":args.total_time.as_secs_f64(),"request_timeout_seconds":args.timeout.as_secs_f64(),"max_retries":args.max_retries,"retry_ambiguous":args.retry_ambiguous,"calibration":args.fixed_calibration,"warmup":warmup,"measurement":measured,"agent_backlog":null,"agent_backlog_stability":"not measured"});
    fs::write(
        &args.fixed_output,
        format!("{}\n", serde_json::to_string_pretty(&output)?),
    )?;
    if let Some(server) = server {
        server.abort();
    }
    Ok(())
}
fn main() -> Result<(), AnyError> {
    let args = Args::parse();
    let mut builder = tokio::runtime::Builder::new_multi_thread();
    builder.enable_all();
    if let Some(n) = args.runtime_threads {
        if n == 0 {
            return Err("runtime-threads must be positive".into());
        }
        builder.worker_threads(n);
    }
    builder.build()?.block_on(run(args))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn closed_dispatch_is_retryable_only_before_any_write_or_response() {
        let (client, _server) = tokio::io::duplex(4096);
        let (mut sender, connection) =
            hyper::client::conn::http1::handshake::<_, Full<Bytes>>(TokioIo::new(client))
                .await
                .unwrap();
        drop(connection);
        let request = Request::post("/")
            .body(Full::new(Bytes::from_static(b"{}")))
            .unwrap();
        let error = sender.send_request(request).await.unwrap_err();
        assert!(error.is_canceled());
        assert!(retryable_request_error(&error, false, false));
        assert!(!retryable_request_error(&error, false, true));
        assert!(!retryable_request_error(&error, true, false));
    }

    #[test]
    fn diagnostics_are_bounded_when_workers_merge() {
        let mut merged = Counters::default();
        for _ in 0..256 {
            let mut worker = Counters::default();
            for _ in 0..20 {
                worker.diagnostic("connection closed".to_owned());
            }
            assert_eq!(worker.error_samples.len(), 8);
            merged.add(worker);
        }
        assert_eq!(merged.error_samples.len(), 8);
    }

    #[tokio::test]
    async fn task_admission_is_bounded_and_pending_expires_without_http() {
        for pending in [0, 2] {
            let args = Arc::new(Args::parse_from([
                "loadgen",
                "--fixed-rate",
                "100",
                "--fixed-payload-file",
                "unused",
                "--fixed-output",
                "unused",
                "--dispatch-mode",
                "tasks",
                "--max-inflight",
                "1",
                "--pending-capacity",
                &pending.to_string(),
            ]));
            let work = Arc::new(Workload {
                args,
                uri: "http://127.0.0.1:1".parse().unwrap(),
                payloads: Arc::new(vec![Bytes::from_static(b"{}\n")]),
                deadline: Instant::now() + Duration::from_millis(30),
                progress: Arc::new(Progress::default()),
            });
            let mut dispatcher = TaskDispatcher::new(work);
            let _held_http = dispatcher.http_slots.clone().acquire_owned().await.unwrap();
            let (_cancel_tx, cancel) = watch::channel(false);
            for index in 0..1 + pending {
                assert!(dispatcher.schedule(index as u64, cancel.clone()));
            }
            assert!(!dispatcher.schedule(100, cancel.clone()));
            assert_eq!(dispatcher.peak_admitted, 1 + pending);
            let mut counts = Counters::default();
            while let Some(result) = dispatcher.tasks.join_next().await {
                counts.add(result.unwrap());
            }
            assert_eq!(counts.expired_before_dispatch_logs as usize, 1 + pending);
            assert_eq!(counts.dispatched_logs, 0);
            assert_eq!(dispatcher.admission.available_permits(), 1 + pending);
            assert_eq!(dispatcher.waiting.load(Relaxed), 0);
        }
    }
    #[tokio::test]
    async fn canceled_pending_tasks_release_all_permits() {
        let args = Arc::new(Args::parse_from([
            "loadgen",
            "--fixed-rate",
            "100",
            "--fixed-payload-file",
            "unused",
            "--fixed-output",
            "unused",
            "--dispatch-mode",
            "tasks",
            "--max-inflight",
            "1",
            "--pending-capacity",
            "1",
        ]));
        let work = Arc::new(Workload {
            args,
            uri: "http://127.0.0.1:1".parse().unwrap(),
            payloads: Arc::new(vec![]),
            deadline: Instant::now() + Duration::from_secs(60),
            progress: Arc::new(Progress::default()),
        });
        let mut dispatcher = TaskDispatcher::new(work);
        let _held = dispatcher.http_slots.clone().acquire_owned().await.unwrap();
        let (tx, cancel) = watch::channel(false);
        assert!(dispatcher.schedule(0, cancel.clone()));
        assert!(dispatcher.schedule(1, cancel));
        tx.send(true).unwrap();
        let mut counts = Counters::default();
        tokio::time::timeout(Duration::from_secs(1), async {
            while let Some(result) = dispatcher.tasks.join_next().await {
                counts.add(result.unwrap());
            }
        })
        .await
        .unwrap();
        assert_eq!(counts.expired_before_dispatch_logs, 2);
        assert_eq!(dispatcher.admission.available_permits(), 2);
        assert_eq!(dispatcher.waiting.load(Relaxed), 0);
    }
    #[test]
    fn rate_budget_and_catchup() {
        for rate in [10000, 25000, 75000, 100000, 200000] {
            assert_eq!(
                due(rate, Duration::from_millis(1), Duration::from_secs(1), 0),
                (rate / 1000, 0)
            );
            assert_eq!(
                due(rate, Duration::from_secs(2), Duration::from_secs(1), 0),
                (rate / 200, rate - rate / 200)
            );
            assert_eq!(due(rate, Duration::ZERO, Duration::from_secs(1), 1), (0, 0));
        }
    }
    #[test]
    fn offered_only_after_complete_body_written() {
        let marker = Arc::new(Marker {
            offered: AtomicBool::new(false),
            deadline: Instant::now() + Duration::from_secs(1),
        });
        let mut state = WriteState::new(3, marker.clone());
        state.observe(b"POST / HTTP/1.1\r\nContent-Length: 3\r\n\r");
        assert!(!marker.offered.load(Relaxed));
        state.observe(b"\na");
        assert!(!marker.offered.load(Relaxed));
        state.observe(b"bc");
        assert!(marker.offered.load(Relaxed));
    }
    #[test]
    fn writes_after_window_are_not_offered() {
        let marker = Arc::new(Marker {
            offered: AtomicBool::new(false),
            deadline: Instant::now() - Duration::from_secs(1),
        });
        WriteState::new(1, marker.clone()).observe(b"POST / HTTP/1.1\r\n\r\nx");
        assert!(!marker.offered.load(Relaxed));
    }
    #[test]
    fn duration_validation() {
        assert_eq!(duration("10ms").unwrap(), Duration::from_millis(10));
        assert!(duration("NaNs").is_err());
        assert!(duration("-1s").is_err());
    }
}
