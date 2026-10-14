// Internal test package: package main cannot be imported.
package main

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/modules/io/clock"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
)

// TestStatusAndStopReachTheDaemonOverTheNetwork serves a daemon on a fake
// network and a fake disk and has se status find it and se stop end it there.
func TestStatusAndStopReachTheDaemonOverTheNetwork(t *testing.T) {
	t.Parallel()
	// se stop polls for the daemon's endpoint to go, which only the real clock
	// waits out while the daemon's goroutine removes it.
	w := worldOf(t)
	w.Net, w.Clock = sehttp.NewFake(), clock.Real()
	d, ws := onFake(t), "/ws"
	fake := clock.NewFake(time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC))
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), daemon.Paths{Workspace: ws, Disk: d}, daemon.Options{
			Clock: fake, Net: w.Net, Modules: modules(daemon.Paths{Workspace: ws, Disk: d}, fake, nil, nil), Ready: func(ep daemon.Endpoint) { ready <- ep },
		})
	}()
	ep := <-ready
	if code, out, errs := se(t, "status", "--workspace", ws); code != 0 || !strings.Contains(out, "answers for "+ws+" at "+ep.Address) {
		t.Fatalf("status: exit %d, %q %q", code, out, errs)
	}
	if code, out, errs := se(t, "stop", "--workspace", ws); code != 0 {
		t.Fatalf("stop: exit %d, %q %q", code, out, errs)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if code, out, _ := se(t, "status", "--workspace", ws); code != 0 || !strings.Contains(out, "No SE daemon answers") {
		t.Fatalf("status after stop: exit %d, %q", code, out)
	}
}
