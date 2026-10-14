package daemon_test

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/clock"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/io/session"
)

// wiring binds the session's modules and the clock as se's wiring file does;
// the daemon's tests start the index on it without the se command's own module.
const wiring = `
instances:
  clock: {module: clock}
  session: {module: session}
  sessionlog: {module: sessionlog}
wires:
  session.events: session/events
  sessionlog.events: session/events
`

// options are a daemon's options on clk and n, its log kept in l, telling ready its endpoint.
func options(clk clock.Clock, n sehttp.Net, l session.Log, ready func(daemon.Endpoint)) daemon.Options {
	w, err := index.ParseWiring([]byte(wiring))
	if err != nil {
		panic(err)
	}
	return daemon.Options{Clock: clk, Net: n, Ready: ready, Wiring: &w, Modules: []*index.Module{clock.Module(clk), session.Posts, session.LogModule(l)}}
}

func withTakeOver(o daemon.Options) daemon.Options { o.TakeOver = 10 * time.Second; return o }

func idling(o daemon.Options) daemon.Options { o.Idle = 30 * time.Minute; return o }

// serving is a daemon's server on a started index, served on a fake network
// behind "tok", its log kept in a fake.
type serving struct {
	t    *testing.T
	n    *sehttp.Fake
	addr string
	log  *session.Fake
}

// served serves a fresh daemon's server on clk until the test ends.
func served(t *testing.T, clk clock.Clock) serving {
	t.Helper()
	s := serving{t: t, n: sehttp.NewFake(), log: session.NewFake()}
	opts := options(clk, s.n, s.log, nil)
	ix, err := index.Start(*opts.Wiring, opts.Modules...)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	addr, done, err := s.n.Serve(ctx, "tok", daemon.NewServer(ix, "i1", nil, clk))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); <-done })
	s.addr = addr
	return s
}

// post sends one event with token and answers its status.
func (s serving) post(token string, ev daemon.Event) int {
	return s.status(s.n.Event(s.addr, token, ev))
}

// value asks for name's value with token and answers it and its status.
func (s serving) value(token, name string) (sehttp.Value, int) {
	v, err := s.n.Value(s.addr, token, name)
	return v, s.status(err)
}

func (s serving) status(err error) int {
	var refused *sehttp.StatusError
	switch {
	case err == nil:
		return sehttp.StatusOK
	case errors.As(err, &refused):
		return refused.Status
	default:
		s.t.Fatal(err)
		return 0
	}
}

func workspace(t *testing.T) daemon.Paths {
	t.Helper()
	p := daemon.Paths{Workspace: t.TempDir()}
	if err := daemon.Prepare(p); err != nil {
		t.Fatal(err)
	}
	return p
}

func rows(t *testing.T, l session.Log, name string) []map[string]any {
	t.Helper()
	b, err := l.Read(name)
	if err != nil {
		t.Fatal(err)
	}
	var out []map[string]any
	sc := bufio.NewScanner(bytes.NewReader(b))
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
	got, err := os.ReadFile(filepath.Join(p.Runtime(), ".gitignore"))
	if err != nil || string(got) != "*\n" {
		t.Fatalf(".gitignore = %q, %v", got, err)
	}
}

func TestAnEventIsAppended(t *testing.T) {
	d := served(t, clock.NewFake(time.Time{}))
	for _, ev := range []string{"session.start", "tool.call"} {
		if code := d.post("tok", daemon.Event{Session: "s1", Event: ev, At: "t", E: json.RawMessage(`{"x":1}`)}); code != sehttp.StatusOK {
			t.Fatalf("%s: status %d", ev, code)
		}
	}
	got := rows(t, d.log, "s1")
	if len(got) != 2 || got[0]["event"] != "session.start" || got[1]["event"] != "tool.call" {
		t.Fatalf("rows = %v", got)
	}
}

func TestAWrongTokenIsRefused(t *testing.T) {
	d := served(t, clock.NewFake(time.Time{}))
	if code := d.post("nope", daemon.Event{Session: "s1", Event: "x"}); code != sehttp.StatusUnauthorized {
		t.Fatalf("status %d", code)
	}
}

func TestASessionNameCannotLeaveTheLogFolder(t *testing.T) {
	d := served(t, clock.NewFake(time.Time{}))
	for _, s := range []string{"../escape", "a/b", "", ".hidden"} {
		if code := d.post("tok", daemon.Event{Session: s, Event: "x"}); code != sehttp.StatusBadRequest {
			t.Fatalf("session %q: status %d", s, code)
		}
	}
}

func TestALongPayloadLandsCut(t *testing.T) {
	d := served(t, clock.NewFake(time.Time{}))
	long := strings.Repeat("a", session.PayloadCap*2)
	d.post("tok", daemon.Event{Session: "s1", Event: "x", E: json.RawMessage(fmt.Sprintf("%q", long))})
	e := rows(t, d.log, "s1")[0]["e"].(map[string]any)
	if e["cut"] != true || int(e["length"].(float64)) != len(long)+2 {
		t.Fatalf("e = %v", e)
	}
}

func TestConcurrentEventsAllLand(t *testing.T) {
	d := served(t, clock.NewFake(time.Time{}))
	var wg sync.WaitGroup
	for i := range 50 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			d.post("tok", daemon.Event{Session: "s1", Event: fmt.Sprintf("e%d", i)})
		}()
	}
	wg.Wait()
	if n := len(rows(t, d.log, "s1")); n != 50 {
		t.Fatalf("%d rows", n)
	}
}

// Two posts alike are two events: each lands as the log module's input, and each is written.
func TestTwoEventsAlikeAreBothWritten(t *testing.T) {
	d := served(t, clock.NewFake(time.Time{}))
	for range 2 {
		d.post("tok", daemon.Event{Session: "s1", Event: "x", At: "t"})
	}
	if n := len(rows(t, d.log, "s1")); n != 2 {
		t.Fatalf("%d rows", n)
	}
}

// The index the daemon hosts answers a name's value over the protocol: the
// clock's start, and the number of the last event the log wrote.
func TestTheDaemonAnswersValuesByName(t *testing.T) {
	at := time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)
	d := served(t, clock.NewFake(at))
	value := func(name string) sehttp.Value {
		t.Helper()
		v, code := d.value("tok", name)
		if code != sehttp.StatusOK {
			t.Fatalf("%s: status %d", name, code)
		}
		return v
	}
	if v := value("clock/started"); v.Value != at.Format(time.RFC3339) || !v.Provided {
		t.Fatalf("clock/started = %v", v)
	}
	if v := value("sessionlog/written"); v.Value != float64(0) {
		t.Fatalf("sessionlog/written before any event = %v", v)
	}
	d.post("tok", daemon.Event{Session: "s1", Event: "x"})
	d.post("tok", daemon.Event{Session: "s2", Event: "y"})
	if v := value("sessionlog/written"); v.Value != float64(2) || !v.Provided {
		t.Fatalf("sessionlog/written after two events = %v", v)
	}
	if _, code := d.value("tok", "no/such"); code != sehttp.StatusNotFound {
		t.Fatalf("a name nothing declares: status %d", code)
	}
	if _, code := d.value("nope", "clock/started"); code != sehttp.StatusUnauthorized {
		t.Fatalf("a wrong token: status %d", code)
	}
}

func TestServePublishesAndWithdrawsItsEndpoint(t *testing.T) {
	p, n := workspace(t), sehttp.NewFake()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, p, options(clock.Real(), n, session.NewFake(), func(ep daemon.Endpoint) { ready <- ep }))
	}()
	ep := <-ready
	if got, ok := daemon.Healthy(p, n); !ok || got.InstanceID != ep.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	if runtime.GOOS != "windows" {
		if err := daemon.Serve(context.Background(), p, options(clock.Real(), n, session.NewFake(), nil)); !errors.Is(err, daemon.ErrRunning) {
			t.Fatalf("second serve: %v", err)
		}
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(p.Endpoint()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("daemon.json stands after the daemon ended: %v", err)
	}
}

func TestStopEndsTheDaemon(t *testing.T) {
	p, n := workspace(t), sehttp.NewFake()
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), p, options(clock.Real(), n, session.NewFake(), func(ep daemon.Endpoint) { ready <- ep }))
	}()
	<-ready
	if err := daemon.Stop(p, 5*time.Second, clock.Real(), n); err != nil {
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
	p, n := workspace(t), sehttp.NewFake()
	f := clock.NewFake(time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC))
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), p, idling(options(f, n, session.NewFake(), func(ep daemon.Endpoint) { ready <- ep })))
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
	if runtime.GOOS == "windows" {
		t.Skip("the lock is not exclusive here")
	}
	p, n := workspace(t), sehttp.NewFake()
	first := make(chan daemon.Endpoint, 1)
	firstDone := make(chan error, 1)
	go func() {
		firstDone <- daemon.Serve(context.Background(), p, options(clock.Real(), n, session.NewFake(), func(ep daemon.Endpoint) { first <- ep }))
	}()
	ep1 := <-first
	ctx, cancel := context.WithCancel(context.Background())
	second := make(chan daemon.Endpoint, 1)
	secondDone := make(chan error, 1)
	go func() {
		secondDone <- daemon.Serve(ctx, p, withTakeOver(options(clock.Real(), n, session.NewFake(), func(ep daemon.Endpoint) { second <- ep })))
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
	if log, err := os.ReadFile(p.DaemonLog()); err != nil || !strings.Contains(string(log), "no port left") {
		t.Fatalf("the daemon's log holds %q (%v)", log, err)
	}
}
