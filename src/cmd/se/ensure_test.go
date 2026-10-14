// Internal test package: package main cannot be imported.
package main

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// ensuring is a workspace on a fake disk whose installed se the fake machine
// does not hold, so every start it tries fails.
func ensuring(t *testing.T) (*World, daemon.Paths, *proc.Fake, *clock.Fake) {
	t.Helper()
	m, clk := proc.NewFake(), clock.NewFake(testedAt)
	m.RunAs("/installed/se")
	w := &World{Clock: clk, Proc: m, Net: sehttp.NewFake()}
	return w, daemon.Paths{Workspace: "/ws", Disk: disk.NewFake()}, m, clk
}

func TestEnsureStartsADaemonFoundDownAtMostOnceAMinute(t *testing.T) {
	t.Parallel()
	w, p, m, clk := ensuring(t)
	first := ensure(w, p)
	if first.Address != "" || first.RetryInMs != 60_000 || !strings.Contains(first.Error, "no such program") || len(m.Ran()) != 1 {
		t.Fatalf("first: %+v, ran %q", first, m.Lines())
	}
	clk.Advance(59 * time.Second)
	if again := ensure(w, p); again.RetryInMs != 1000 || again.Error != "" || len(m.Ran()) != 1 {
		t.Fatalf("within the minute: %+v, ran %q", again, m.Lines())
	}
	clk.Advance(time.Second)
	if later := ensure(w, p); later.RetryInMs != 60_000 || len(m.Ran()) != 2 {
		t.Fatalf("after the minute: %+v, ran %q", later, m.Lines())
	}
}

func TestEnsureWaitsOutAStartTheSessionAskedFor(t *testing.T) {
	t.Parallel()
	w, p, m, clk := ensuring(t)
	// /se on tried a start just now; ensure does not try another.
	if _, _, err := startDaemon(w, p); err == nil {
		t.Fatal("the start found a se the machine does not hold")
	}
	clk.Advance(10 * time.Second)
	if said := ensure(w, p); said.RetryInMs != 50_000 || len(m.Ran()) != 1 {
		t.Fatalf("%+v, ran %q", said, m.Lines())
	}
}

func TestEnsureAnswersTheDaemonWhereverItMoved(t *testing.T) {
	t.Parallel()
	w, p, m, _ := ensuring(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, p, daemon.Options{Clock: clock.Real(), Net: w.Net, Ready: func(ep daemon.Endpoint) { ready <- ep }})
	}()
	ep := <-ready
	t.Cleanup(func() {
		cancel()
		<-done
	})
	if said := ensure(w, p); said.Address != ep.Address || said.Token != ep.Token || len(m.Ran()) != 0 {
		t.Fatalf("%+v, want %s; ran %q", said, ep.Address, m.Lines())
	}
}

func TestEnsureStartsNothingWhileAnotherStartHoldsTheLock(t *testing.T) {
	t.Parallel()
	w, p, m, _ := ensuring(t)
	if err := daemon.Prepare(p); err != nil {
		t.Fatal(err)
	}
	held, err := p.Disk.Lock(p.Starting())
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	said := ensure(w, p)
	if said.Address != "" || said.Error == "" || len(m.Ran()) != 0 {
		t.Fatalf("%+v, ran %q", said, m.Lines())
	}
}
