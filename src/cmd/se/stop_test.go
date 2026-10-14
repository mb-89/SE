// Internal test package: package main cannot be imported.
package main

import (
	"context"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/io/clock"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
)

// TestStatusAndStopReachTheDaemonOverTheNetwork serves a daemon on a fake
// network and has se status find it and se stop end it there.
func TestStatusAndStopReachTheDaemonOverTheNetwork(t *testing.T) {
	old := network
	network = sehttp.NewFake()
	t.Cleanup(func() { network = old })
	ws := t.TempDir()
	paths := daemon.Paths{Workspace: ws}
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), paths, daemon.Options{
			Clock: clock.Real(), Net: network, Modules: modules(paths, clock.Real()), Ready: func(ep daemon.Endpoint) { ready <- ep },
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
