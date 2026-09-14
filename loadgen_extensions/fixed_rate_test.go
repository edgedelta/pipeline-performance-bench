package main

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

func TestFixedGlobalBudgetAndBoundedCatchup(t *testing.T) {
	for _, rate := range []int{10000, 25000, 50000, 75000} {
		var total int64
		for tick := 1; tick <= 1000; tick++ {
			due, missed := fixedDue(rate, time.Duration(tick)*time.Millisecond, time.Second, total)
			if missed != 0 {
				t.Fatal("regular clock missed tokens")
			}
			total += due
		}
		if total != int64(rate) {
			t.Fatalf("rate=%d scheduled=%d", rate, total)
		}
		due, missed := fixedDue(rate, time.Second, time.Second, 0)
		if due > int64(rate)/200 || due+missed != int64(rate) {
			t.Fatal("unbounded catchup or missing accounting")
		}
		due, missed = fixedDue(rate, 2*time.Second, time.Second, int64(rate))
		if due != 0 || missed != 0 {
			t.Fatal("tokens beyond window")
		}
	}
}

func assertFixedAccounting(t *testing.T, p fixedPhase) {
	t.Helper()
	if p.Dispatched+p.SchedulerMissed+p.QueueDropped+p.Expired != p.Scheduled {
		t.Fatalf("scheduled accounting: %+v", p)
	}
	if p.Ack+p.AckAfter+p.Errors != p.Dispatched || p.Backpressure > p.Errors {
		t.Fatalf("outcome accounting: %+v", p)
	}
	if p.Ack > p.Offered || p.Offered > p.Dispatched || p.InflightAfter != 0 {
		t.Fatalf("window/drain accounting: %+v", p)
	}
}

func TestFixedWorkersDoNotMultiplyRate(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		r.Body.Close()
		w.WriteHeader(200)
	}))
	defer server.Close()
	for _, workers := range []int{1, 16, 256} {
		cfg := &Config{Endpoint: server.URL, Workers: workers, Timeout: time.Second, MaxRetries: 2, RetryAmbiguous: true}
		p := fixedPhaseRun(context.Background(), cfg, 200, time.Second, [][]byte{[]byte(`{"message":"test"}`)}, "")
		assertFixedAccounting(t, p)
		if p.Offered > 200 || p.Offered < 180 || p.Ack < 180 || p.Errors != 0 {
			t.Fatalf("workers=%d offered=%d ack=%d errors=%d", workers, p.Offered, p.Ack, p.Errors)
		}
	}
}

func TestFixedBackpressureAndClientQueueAreDistinct(t *testing.T) {
	for _, status := range []int{200, 429, 400} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			io.Copy(io.Discard, r.Body)
			time.Sleep(30 * time.Millisecond)
			w.WriteHeader(status)
		}))
		cfg := &Config{Endpoint: server.URL, Workers: 1, Timeout: time.Second, MaxRetries: 2, RetryAmbiguous: true}
		p := fixedPhaseRun(context.Background(), cfg, 1000, 200*time.Millisecond, [][]byte{[]byte(`{}`)}, "")
		server.Close()
		assertFixedAccounting(t, p)
		if p.QueueDropped == 0 || p.Retries != 0 {
			t.Fatalf("missing queue drops or retried HTTP status: %+v", p)
		}
		if status == 429 && (p.Backpressure == 0 || p.Backpressure != p.Errors) {
			t.Fatal("lost backpressure")
		}
		if status == 200 && (p.AckAfter == 0 || p.Errors != 0) {
			t.Fatal("post-window acknowledgements not separated")
		}
		if status == 400 && (p.Errors == 0 || p.HTTPStatuses[400] == 0) {
			t.Fatal("lost configuration rejection")
		}
	}
}

func TestFixedRotationPreservesRetryAccounting(t *testing.T) {
	var count atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		if count.Add(1)%2 == 1 {
			c, _, _ := w.(http.Hijacker).Hijack()
			c.Close()
			return
		}
		w.WriteHeader(200)
	}))
	defer server.Close()
	p := fixedPhaseRun(context.Background(), &Config{Endpoint: server.URL, Workers: 1, Timeout: time.Second, MaxRetries: 2, RetryAmbiguous: true}, 20, time.Second, [][]byte{[]byte(`{}`)}, "")
	assertFixedAccounting(t, p)
	if p.Connections == 0 || p.Retries == 0 || p.Recovered == 0 || p.Ambiguous == 0 {
		t.Fatalf("retry accounting lost: %+v", p)
	}
}

func TestFixedResourceInspectionMissingAndRealCounters(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "cpu.stat"), []byte("usage_usec 1234\nuser_usec 900\n"), 0600)
	os.WriteFile(filepath.Join(dir, "memory.current"), []byte("1000000\n"), 0600)
	s := fixedResource(dir, 1)
	if s.CPU == nil || *s.CPU != 1234 || s.Memory == nil || *s.Memory != 1000000 {
		t.Fatal(s)
	}
	s = fixedResource(filepath.Join(dir, "missing"), 1)
	if s.CPU != nil || s.Memory != nil {
		t.Fatal("fabricated missing counters")
	}
}

func TestFixedCancellationIsInvalidatable(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	p := fixedPhaseRun(ctx, &Config{Endpoint: "http://127.0.0.1:1", Workers: 1, Timeout: time.Second}, 100, time.Second, [][]byte{[]byte(`{}`)}, "")
	if !p.Canceled || p.Ack != 0 {
		t.Fatal(p)
	}
	assertFixedAccounting(t, p)
}
