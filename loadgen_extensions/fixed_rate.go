package main

// Fixed-rate mode is separate from the inherited best-throughput workload.
// One scheduler controls the TOTAL offered workload; workers never mint tokens.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/http/httptrace"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

var fixedRate = flag.Int("fixed-rate", 0, "TOTAL logical input logs/sec across all workers; separate fixed-rate mode")
var fixedOutput = flag.String("fixed-output", "", "Raw fixed-rate JSON output")
var fixedPayload = flag.String("fixed-payload-file", "", "Identical NDJSON corpus; one line per HTTP request")
var fixedCgroup = flag.String("fixed-cgroup", "", "Agent cgroup v2 directory for whole-service measurement")
var fixedWarmup = flag.Duration("fixed-warmup", 10*time.Second, "Offered-load warm-up, excluded from measurement")
var fixedCalibration = flag.Bool("fixed-calibration", false, "Measure this generator against a local acknowledgement server")

type fixedSample struct {
	Elapsed   float64 `json:"elapsed_seconds"`
	CPU       *int64  `json:"agent_cpu_usage_usec"`
	Memory    *int64  `json:"agent_memory_bytes"`
	SelfCPU   *int64  `json:"generator_cpu_usage_usec"`
	SelfRSS   *int64  `json:"generator_rss_bytes"`
	HostBusy  *uint64 `json:"host_busy_ticks"`
	HostTotal *uint64 `json:"host_total_ticks"`
}

type fixedPhase struct {
	Duration        float64       `json:"duration_seconds"`
	Scheduled       int64         `json:"scheduled_logs"`
	Dispatched      int64         `json:"dispatched_logs"`
	Offered         int64         `json:"offered_logs"`
	Ack             int64         `json:"acknowledged_logs"`
	AckAfter        int64         `json:"acknowledged_after_window"`
	Errors          int64         `json:"errors"`
	Backpressure    int64         `json:"backpressure"`
	Connections     int64         `json:"connection_errors"`
	Retries         int64         `json:"retry_attempts"`
	Recovered       int64         `json:"recovered_requests"`
	Ambiguous       int64         `json:"ambiguous_deliveries"`
	SchedulerMissed int64         `json:"scheduler_missed_logs"`
	QueueDropped    int64         `json:"worker_queue_dropped_logs"`
	Expired         int64         `json:"expired_before_dispatch_logs"`
	InflightEnd     int64         `json:"client_inflight_at_end"`
	InflightAfter   int64         `json:"client_inflight_after_drain"`
	QueueEnd        int           `json:"client_queue_at_end"`
	Drain           float64       `json:"http_drain_seconds"`
	LatencyMean     float64       `json:"mean_response_latency_ms"`
	Samples         []fixedSample `json:"resource_samples"`
	HTTPStatuses    map[int]int64 `json:"http_status_counts"`
	Canceled        bool          `json:"canceled"`
}

func fixedReadInt(path string) *int64 {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	n, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	if err != nil {
		return nil
	}
	return &n
}
func fixedResource(cgroup string, elapsed float64) fixedSample {
	s := fixedSample{Elapsed: elapsed}
	if cgroup != "" {
		if b, err := os.ReadFile(filepath.Join(cgroup, "cpu.stat")); err == nil {
			fields := strings.Fields(string(b))
			for i := 0; i+1 < len(fields); i += 2 {
				if fields[i] == "usage_usec" {
					n, e := strconv.ParseInt(fields[i+1], 10, 64)
					if e == nil {
						s.CPU = &n
					}
				}
			}
		}
		s.Memory = fixedReadInt(filepath.Join(cgroup, "memory.current"))
	}
	var u syscall.Rusage
	if syscall.Getrusage(syscall.RUSAGE_SELF, &u) == nil {
		n := int64(u.Utime.Sec)*1000000 + int64(u.Utime.Usec) + int64(u.Stime.Sec)*1000000 + int64(u.Stime.Usec)
		s.SelfCPU = &n
	}
	if b, e := os.ReadFile("/proc/self/statm"); e == nil {
		f := strings.Fields(string(b))
		if len(f) > 1 {
			n, e := strconv.ParseInt(f[1], 10, 64)
			if e == nil {
				n *= int64(os.Getpagesize())
				s.SelfRSS = &n
			}
		}
	}
	if b, e := os.ReadFile("/proc/stat"); e == nil {
		f := strings.Fields(strings.SplitN(string(b), "\n", 2)[0])
		if len(f) >= 9 {
			var total, idle uint64
			good := true
			for i := 1; i <= 8; i++ {
				n, e := strconv.ParseUint(f[i], 10, 64)
				if e != nil {
					good = false
				}
				total += n
				if i == 4 || i == 5 {
					idle += n
				}
			}
			if good {
				busy := total - idle
				s.HostBusy = &busy
				s.HostTotal = &total
			}
		}
	}
	return s
}

// Up to 5ms of catch-up is allowed; longer scheduler stalls are recorded,
// never converted into a later unbounded burst or hidden by slowing the clock.
func fixedDue(rate int, elapsed, duration time.Duration, accounted int64) (due, missed int64) {
	if elapsed > duration {
		elapsed = duration
	}
	if elapsed < 0 {
		return 0, 0
	}
	total := int64(float64(rate) * elapsed.Seconds())
	due = total - accounted
	if due < 0 {
		return 0, 0
	}
	burst := int64(math.Ceil(float64(rate) * 0.005))
	if burst < 1 {
		burst = 1
	}
	if due > burst {
		missed = due - burst
		due = burst
	}
	return
}

func fixedPhaseRun(ctx context.Context, cfg *Config, rate int, duration time.Duration, payloads [][]byte, cgroup string) fixedPhase {
	stats := &Stats{}
	base := &http.Transport{MaxIdleConns: cfg.Workers, MaxIdleConnsPerHost: cfg.Workers, DisableCompression: true, IdleConnTimeout: 90 * time.Second}
	fresh := base.Clone()
	fresh.DisableKeepAlives = true
	transport := &retryTransport{base: base, fresh: fresh, stats: stats, maxRetries: cfg.MaxRetries, retryAmbiguous: cfg.RetryAmbiguous}
	defer transport.CloseIdleConnections()
	client := &http.Client{Timeout: cfg.Timeout, Transport: transport, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
	start := time.Now()
	deadline := start.Add(duration)
	var dispatched, offered, ack, completed, expired, latency atomic.Int64
	var wg sync.WaitGroup
	var statusMu sync.Mutex
	statuses := map[int]int64{}
	queue := make(chan int64, cfg.Workers)
	for i := 0; i < cfg.Workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range queue {
				if !time.Now().Before(deadline) || ctx.Err() != nil {
					expired.Add(1)
					continue
				}
				dispatched.Add(1)
				body := payloads[index%int64(len(payloads))]
				req, err := http.NewRequestWithContext(ctx, "POST", cfg.Endpoint, bytes.NewReader(body))
				if err != nil {
					stats.recordError(len(body))
					completed.Add(1)
					continue
				}
				req.Header.Set("Content-Type", "application/json")
				var written atomic.Bool
				trace := &httptrace.ClientTrace{WroteRequest: func(info httptrace.WroteRequestInfo) {
					if info.Err == nil && !written.Swap(true) && time.Now().Before(deadline) {
						offered.Add(1)
					}
				}}
				req = req.WithContext(httptrace.WithClientTrace(req.Context(), trace))
				sent := time.Now()
				resp, err := client.Do(req)
				if err != nil {
					stats.recordError(len(body))
				} else {
					statusMu.Lock()
					statuses[resp.StatusCode]++
					statusMu.Unlock()
					_, readErr := io.Copy(io.Discard, resp.Body)
					_ = resp.Body.Close()
					if readErr != nil {
						stats.recordError(len(body))
					} else if resp.StatusCode == 429 || resp.StatusCode == 503 {
						stats.recordBackpressure(len(body))
					} else if resp.StatusCode >= 400 {
						stats.recordError(len(body))
					} else {
						stats.recordSuccess(len(body))
						if time.Now().Before(deadline) {
							ack.Add(1)
						}
					}
				}
				latency.Add(time.Since(sent).Nanoseconds())
				completed.Add(1)
			}
		}()
	}
	result := fixedPhase{Samples: []fixedSample{fixedResource(cgroup, 0)}}
	ticker := time.NewTicker(time.Millisecond)
	defer ticker.Stop()
	sampleTicker := time.NewTicker(time.Second)
	defer sampleTicker.Stop()
	timer := time.NewTimer(duration)
	defer timer.Stop()
	var accounted int64
	running := true
	for running {
		select {
		case <-ctx.Done():
			result.Canceled = true
			running = false
		case <-timer.C:
			running = false
		case <-sampleTicker.C:
			result.Samples = append(result.Samples, fixedResource(cgroup, time.Since(start).Seconds()))
		case <-ticker.C:
			due, missed := fixedDue(rate, time.Since(start), duration, accounted)
			result.SchedulerMissed += missed
			accounted += missed
			for j := int64(0); j < due; j++ {
				select {
				case queue <- accounted:
				default:
					result.QueueDropped++
				}
				accounted++
			}
		}
	}
	result.Duration = time.Since(start).Seconds()
	result.Samples = append(result.Samples, fixedResource(cgroup, result.Duration))
	result.Scheduled = int64(float64(rate) * duration.Seconds())
	// Any final fractional scheduling window is explicitly accounted for.
	if result.Scheduled > accounted {
		result.SchedulerMissed += result.Scheduled - accounted
	}
	result.InflightEnd = dispatched.Load() - completed.Load()
	result.QueueEnd = len(queue)
	close(queue)
	drainStart := time.Now()
	wg.Wait()
	result.Drain = time.Since(drainStart).Seconds()
	result.HTTPStatuses = statuses
	result.Dispatched = dispatched.Load()
	result.Offered = offered.Load()
	result.Ack = ack.Load()
	result.Expired = expired.Load()
	result.InflightAfter = dispatched.Load() - completed.Load()
	stats.mu.Lock()
	result.AckAfter = stats.successfulLogs - result.Ack
	result.Errors = stats.httpErrors
	result.Backpressure = stats.backpressureCount
	result.Connections = stats.connectionErrors
	result.Retries = stats.retryAttempts
	result.Recovered = stats.recoveredRequests
	result.Ambiguous = stats.ambiguousDeliveries
	stats.mu.Unlock()
	if completed.Load() > 0 {
		result.LatencyMean = float64(latency.Load()) / float64(completed.Load()) / 1e6
	}
	return result
}

func runFixed(cfg *Config) error {
	if *fixedRate <= 0 || cfg.Workers < 1 || cfg.Number != 1 || cfg.TotalTime <= 0 || *fixedWarmup < 0 || cfg.Timeout <= 0 || *fixedOutput == "" || *fixedPayload == "" {
		return fmt.Errorf("fixed mode requires positive rate/workers/duration/timeout, number=1, payload and output")
	}
	raw, err := os.ReadFile(*fixedPayload)
	if err != nil {
		return err
	}
	lines := bytes.Split(bytes.TrimSpace(raw), []byte{'\n'})
	payloads := make([][]byte, 0, len(lines))
	for _, line := range lines {
		if !json.Valid(line) {
			return fmt.Errorf("invalid corpus NDJSON")
		}
		payloads = append(payloads, append(append([]byte{}, line...), '\n'))
	}
	if len(payloads) == 0 {
		return fmt.Errorf("empty corpus")
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if *fixedCalibration {
		listener, e := net.Listen("tcp", "127.0.0.1:0")
		if e != nil {
			return e
		}
		server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body)
			_ = r.Body.Close()
			w.WriteHeader(200)
		}), ReadHeaderTimeout: 5 * time.Second}
		go func() { _ = server.Serve(listener) }()
		defer server.Close()
		cfg.Endpoint = "http://" + listener.Addr().String()
	}
	warmup := fixedPhase{}
	if *fixedWarmup > 0 {
		warmup = fixedPhaseRun(ctx, cfg, *fixedRate, *fixedWarmup, payloads, *fixedCgroup)
	}
	measured := fixedPhaseRun(ctx, cfg, *fixedRate, cfg.TotalTime, payloads, *fixedCgroup)
	hash := sha256.Sum256(raw)
	output := map[string]any{"schema_version": 2, "target_logs_per_second": *fixedRate, "workers": cfg.Workers, "payload_sha256": hex.EncodeToString(hash[:]), "warmup_seconds": fixedWarmup.Seconds(), "configured_measurement_seconds": cfg.TotalTime.Seconds(), "request_timeout_seconds": cfg.Timeout.Seconds(), "max_retries": cfg.MaxRetries, "retry_ambiguous": cfg.RetryAmbiguous, "calibration": *fixedCalibration, "warmup": warmup, "measurement": measured, "agent_backlog": nil, "agent_backlog_stability": "not measured"}
	b, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(*fixedOutput, append(b, '\n'), 0644)
}
