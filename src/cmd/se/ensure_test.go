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
func ensuring(t *testing.T) (daemon.Paths, *proc.Fake, *clock.Fake) {
	t.Helper()
	was := executable
	executable = func() (string, error) { return "/installed/se", nil }
	t.Cleanup(func() { executable = was })
	return daemon.Paths{Workspace: "/ws", Disk: disk.NewFake()}, proc.NewFake(), clock.NewFake(time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC))
}

func TestEnsureStartsADaemonFoundDownAtMostOnceAMinute(t *testing.T) {
	p, m, clk := ensuring(t)
	net := sehttp.NewFake()
	first := ensure(m, p, clk, net)
	if first.Address != "" || first.RetryInMs != 60_000 || !strings.Contains(first.Error, "no such program") || len(m.Ran()) != 1 {
		t.Fatalf("first: %+v, ran %q", first, m.Lines())
	}
	clk.Advance(59 * time.Second)
	if again := ensure(m, p, clk, net); again.RetryInMs != 1000 || again.Error != "" || len(m.Ran()) != 1 {
		t.Fatalf("within the minute: %+v, ran %q", again, m.Lines())
	}
	clk.Advance(time.Second)
	if later := ensure(m, p, clk, net); later.RetryInMs != 60_000 || len(m.Ran()) != 2 {
		t.Fatalf("after the minute: %+v, ran %q", later, m.Lines())
	}
}

func TestEnsureWaitsOutAStartTheSessionAskedFor(t *testing.T) {
	p, m, clk := ensuring(t)
	net := sehttp.NewFake()
	// /se on tried a start just now; ensure does not try another.
	if _, _, err := startDaemon(m, p, clk, net); err == nil {
		t.Fatal("the start found a se the machine does not hold")
	}
	clk.Advance(10 * time.Second)
	if said := ensure(m, p, clk, net); said.RetryInMs != 50_000 || len(m.Ran()) != 1 {
		t.Fatalf("%+v, ran %q", said, m.Lines())
	}
}

func TestEnsureAnswersTheDaemonWhereverItMoved(t *testing.T) {
	p, m, clk := ensuring(t)
	net := sehttp.NewFake()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, p, daemon.Options{Clock: clock.Real(), Net: net, Ready: func(ep daemon.Endpoint) { ready <- ep }})
	}()
	ep := <-ready
	t.Cleanup(func() {
		cancel()
		<-done
	})
	if said := ensure(m, p, clk, net); said.Address != ep.Address || said.Token != ep.Token || len(m.Ran()) != 0 {
		t.Fatalf("%+v, want %s; ran %q", said, ep.Address, m.Lines())
	}
}

func TestEnsureStartsNothingWhileAnotherStartHoldsTheLock(t *testing.T) {
	p, m, clk := ensuring(t)
	if err := daemon.Prepare(p); err != nil {
		t.Fatal(err)
	}
	held, err := p.Disk.Lock(p.Starting())
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	said := ensure(m, p, clk, sehttp.NewFake())
	if said.Address != "" || said.Error == "" || len(m.Ran()) != 0 {
		t.Fatalf("%+v, ran %q", said, m.Lines())
	}
}
