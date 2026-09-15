// Common external acknowledgment receiver for local generator comparisons.
package main

import (
	"encoding/json"
	"flag"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

func main() {
	address := flag.String("listen", "127.0.0.1:18080", "listen address")
	flag.Parse()
	var requests, bytes atomic.Uint64
	http.HandleFunc("/ingest", func(w http.ResponseWriter, r *http.Request) {
		n, err := io.Copy(io.Discard, r.Body)
		if err != nil {
			http.Error(w, "incomplete body", 400)
			return
		}
		bytes.Add(uint64(n))
		requests.Add(1)
		w.Header().Set("Content-Length", "0")
		w.WriteHeader(200)
	})
	http.HandleFunc("/stats", func(w http.ResponseWriter, r *http.Request) {
		var usage syscall.Rusage
		_ = syscall.Getrusage(syscall.RUSAGE_SELF, &usage)
		cpu := usage.Utime.Sec*1000000 + int64(usage.Utime.Usec) + usage.Stime.Sec*1000000 + int64(usage.Stime.Usec)
		var rss uint64
		if raw, err := os.ReadFile("/proc/self/statm"); err == nil {
			fields := strings.Fields(string(raw))
			if len(fields) > 1 {
				pages, _ := strconv.ParseUint(fields[1], 10, 64)
				rss = pages * uint64(os.Getpagesize())
			}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"requests": requests.Load(), "bytes": bytes.Load(), "cpu_usec": cpu, "rss_bytes": rss, "unix_seconds": float64(time.Now().UnixNano()) / 1e9})
	})
	log.Fatal(http.ListenAndServe(*address, nil))
}
