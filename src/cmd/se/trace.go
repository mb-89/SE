package main

import (
	"fmt"
	"io"
	"sort"
	"sync"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
)

// tracer keeps each GitHub request a run of se --trace makes, to print once
// the command is done: how a command's cold path is measured, and which
// requests sit on its critical path.
type tracer struct {
	clock clock.Clock
	start time.Time
	mu    sync.Mutex
	asked []github.Request
}

func (t *tracer) seen(r github.Request) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.asked = append(t.asked, r)
}

// print writes the trace: the run's wall time and request count, then each
// request by its start, its start and duration in seconds from the run's
// start, its status, method and path.
func (t *tracer) print(w io.Writer) {
	t.mu.Lock()
	defer t.mu.Unlock()
	sort.SliceStable(t.asked, func(i, j int) bool { return t.asked[i].Start.Before(t.asked[j].Start) })
	fmt.Fprintf(w, "se --trace: %.2fs, %d GitHub requests\n", t.clock.Now().Sub(t.start).Seconds(), len(t.asked))
	for _, r := range t.asked {
		fmt.Fprintf(w, "%6.2f %5.2f %3d %s %s\n", r.Start.Sub(t.start).Seconds(), r.Took.Seconds(), r.Status, r.Method, r.Path)
	}
}
