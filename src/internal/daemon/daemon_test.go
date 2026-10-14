package daemon_test

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/io/proc"

	"github.com/mb-89/SE/src/internal/daemon"
)

func workspace(t *testing.T) daemon.Paths {
	t.Helper()
	p := daemon.Paths{Workspace: filepath.FromSlash("/ws"), Disk: disk.NewFake()}
	if err := daemon.Prepare(p); err != nil {
		t.Fatal(err)
	}
	return p
}

// served serves a fresh daemon for p on a fake network behind "tok" until
// the test ends, and answers a post that sends one event with token and
// answers its status.
func served(t *testing.T, p daemon.Paths) func(token string, ev daemon.Event) int {
	t.Helper()
	n := sehttp.NewFake()
	ctx, cancel := context.WithCancel(context.Background())
	addr, done, err := n.Serve(ctx, "tok", daemon.NewServer(p, "i1", nil, clock.NewFake(time.Time{})))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); <-done })
	return func(token string, ev daemon.Event) int {
		var refused *sehttp.StatusError
		switch err := n.Event(addr, token, ev); {
		case err == nil:
			return sehttp.StatusOK
		case errors.As(err, &refused):
			return refused.Status
		default:
			t.Fatal(err)
			return 0
		}
	}
}

func rows(t *testing.T, p daemon.Paths, session string) []map[string]any {
	t.Helper()
	log, err := p.Disk.ReadFile(filepath.Join(p.Logs(), session+".jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	var out []map[string]any
	sc := bufio.NewScanner(bytes.NewReader(log))
	sc.Buffer(nil, 1<<20)
	for sc.Scan() {
		var row map[string]any
		if err := json.Unmarshal(sc.Bytes(), &row); err != nil {
			t.Fatalf("row %q: %v", sc.Text(), err)
		}
		out = append(out, row)
	}
	return out
}

func TestPrepareIgnoresTheRuntimeFolder(t *testing.T) {
	p := workspace(t)
	got, err := p.Disk.ReadFile(filepath.Join(p.Runtime(), ".gitignore"))
	if err != nil || string(got) != "*\n" {
		t.Fatalf(".gitignore = %q, %v", got, err)
	}
}

func TestAnEventIsAppended(t *testing.T) {
	p := workspace(t)
	post := served(t, p)
	for _, ev := range []string{"session.start", "tool.call"} {
		if code := post("tok", daemon.Event{Session: "s1", Event: ev, At: "t", E: json.RawMessage(`{"x":1}`)}); code != sehttp.StatusOK {
			t.Fatalf("%s: status %d", ev, code)
		}
	}
	got := rows(t, p, "s1")
	if len(got) != 2 || got[0]["event"] != "session.start" || got[1]["event"] != "tool.call" {
		t.Fatalf("rows = %v", got)
	}
}

func TestAWrongTokenIsRefused(t *testing.T) {
	p := workspace(t)
	post := served(t, p)
	if code := post("nope", daemon.Event{Session: "s1", Event: "x"}); code != sehttp.StatusUnauthorized {
		t.Fatalf("status %d", code)
	}
}

func TestASessionNameCannotLeaveTheLogFolder(t *testing.T) {
	p := workspace(t)
	post := served(t, p)
	for _, s := range []string{"../escape", "a/b", "", ".hidden"} {
		if code := post("tok", daemon.Event{Session: s, Event: "x"}); code != sehttp.StatusBadRequest {
			t.Fatalf("session %q: status %d", s, code)
		}
	}
}

func TestALongPayloadLandsCut(t *testing.T) {
	p := workspace(t)
	post := served(t, p)
	long := strings.Repeat("a", daemon.PayloadCap*2)
	post("tok", daemon.Event{Session: "s1", Event: "x", E: json.RawMessage(fmt.Sprintf("%q", long))})
	e := rows(t, p, "s1")[0]["e"].(map[string]any)
	if e["cut"] != true || int(e["length"].(float64)) != len(long)+2 {
		t.Fatalf("e = %v", e)
	}
}

func TestConcurrentEventsAllLand(t *testing.T) {
	p := workspace(t)
	post := served(t, p)
	var wg sync.WaitGroup
	for i := range 50 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			post("tok", daemon.Event{Session: "s1", Event: fmt.Sprintf("e%d", i)})
		}()
	}
	wg.Wait()
	if n := len(rows(t, p, "s1")); n != 50 {
		t.Fatalf("%d rows", n)
	}
}

// at is the time the fake clocks of these tests stand at.
var at = time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)

func TestServePublishesAndWithdrawsItsEndpoint(t *testing.T) {
	p, n, f := workspace(t), sehttp.NewFake(), clock.NewFake(at)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, p, daemon.Options{Clock: f, Net: n, Ready: func(ep daemon.Endpoint) { ready <- ep }})
	}()
	ep := <-ready
	if got, ok := daemon.Healthy(p, n); !ok || got.InstanceID != ep.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	if err := daemon.Serve(context.Background(), p, daemon.Options{Clock: f, Net: n}); !errors.Is(err, daemon.ErrRunning) {
		t.Fatalf("second serve: %v", err)
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if there, err := p.Disk.Exists(p.Endpoint()); there || err != nil {
		t.Fatalf("daemon.json stands after the daemon ended: %v", err)
	}
}

func TestStopEndsTheDaemon(t *testing.T) {
	p, n, f := workspace(t), sehttp.NewFake(), clock.NewFake(at)
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), p, daemon.Options{Clock: f, Net: n, Ready: func(ep daemon.Endpoint) { ready <- ep }})
	}()
	<-ready
	// The fake's sleeps pass at once: a day of them leaves the daemon time to withdraw.
	if err := daemon.Stop(p, 24*time.Hour, f, n); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if _, ok := daemon.Healthy(p, n); ok {
		t.Fatal("still healthy after stop")
	}
}

func TestAnIdleDaemonEnds(t *testing.T) {
	p := workspace(t)
	f := clock.NewFake(at)
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), p, daemon.Options{Idle: 30 * time.Minute, Clock: f, Net: sehttp.NewFake(), Ready: func(ep daemon.Endpoint) { ready <- ep }})
	}()
	<-ready
	// ended moves the fake clock on a minute and says whether the daemon has ended.
	ended := func() bool {
		f.Advance(time.Minute)
		runtime.Gosched()
		select {
		case err := <-done:
			if err != nil {
				t.Fatal(err)
			}
			return true
		default:
			return false
		}
	}
	for range 29 {
		if ended() {
			t.Fatalf("the daemon ended at %v, before its idle half hour", f.Now())
		}
	}
	for range 1_000_000 {
		if ended() {
			return
		}
	}
	t.Fatal("the daemon did not idle out")
}

func TestTakeOverStepsARunningDaemonAside(t *testing.T) {
	p, n, f := workspace(t), sehttp.NewFake(), clock.NewFake(at)
	first := make(chan daemon.Endpoint, 1)
	firstDone := make(chan error, 1)
	go func() {
		firstDone <- daemon.Serve(context.Background(), p, daemon.Options{Clock: f, Net: n, Ready: func(ep daemon.Endpoint) { first <- ep }})
	}()
	ep1 := <-first
	ctx, cancel := context.WithCancel(context.Background())
	second := make(chan daemon.Endpoint, 1)
	secondDone := make(chan error, 1)
	go func() {
		// A day on the fake, whose sleeps pass at once, as in TestStopEndsTheDaemon.
		secondDone <- daemon.Serve(ctx, p, daemon.Options{Clock: f, Net: n, TakeOver: 24 * time.Hour, Ready: func(ep daemon.Endpoint) { second <- ep }})
	}()
	ep2 := <-second
	if err := <-firstDone; err != nil {
		t.Fatal(err)
	}
	if got, ok := daemon.Healthy(p, n); !ok || got.InstanceID != ep2.InstanceID || ep2.InstanceID == ep1.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	cancel()
	if err := <-secondDone; err != nil {
		t.Fatal(err)
	}
}

func TestStartRunsTheDaemonDetachedAndSaysWhenItExits(t *testing.T) {
	t.Parallel()
	p := workspace(t)
	m := proc.NewFake()
	m.Install("/bin/se", func(c proc.Cmd) int {
		fmt.Fprintln(c.Stderr, "se serve: no port left")
		return 1
	})
	_, err := daemon.Start(m, p, "/bin/se", time.Minute, clock.NewFake(time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)), sehttp.NewFake())
	if err == nil || !strings.Contains(err.Error(), "the daemon exited at start (exit status 1)") {
		t.Fatalf("%v", err)
	}
	ran := m.Ran()
	if len(ran) != 1 || ran[0].String() != "/bin/se serve --workspace "+p.Workspace || !ran[0].Detached {
		t.Fatalf("ran %+v", ran)
	}
	if log, err := p.Disk.ReadFile(p.DaemonLog()); err != nil || !strings.Contains(string(log), "no port left") {
		t.Fatalf("the daemon's log holds %q (%v)", log, err)
	}
}
