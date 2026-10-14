package daemon_test

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
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

// options are a daemon's options on clk, its log kept in l, telling ready its endpoint.
func options(clk clock.Clock, l session.Log, ready func(daemon.Endpoint)) daemon.Options {
	w, err := index.ParseWiring([]byte(wiring))
	if err != nil {
		panic(err)
	}
	return daemon.Options{Clock: clk, Ready: ready, Wiring: &w, Modules: []*index.Module{clock.Module(clk), session.Posts, session.LogModule(l)}}
}

// server is a daemon's handler on a started index, its log kept in a fake.
func server(t *testing.T, clk clock.Clock) (http.Handler, *session.Fake) {
	t.Helper()
	l := session.NewFake()
	opts := options(clk, l, nil)
	ix, err := index.Start(*opts.Wiring, opts.Modules...)
	if err != nil {
		t.Fatal(err)
	}
	return daemon.NewServer(ix, "tok", "i1", nil, clk).Handler(), l
}

func withTakeOver(o daemon.Options) daemon.Options { o.TakeOver = 10 * time.Second; return o }

func idling(o daemon.Options) daemon.Options { o.Idle = 30 * time.Minute; return o }

// get answers a GET's status and body.
func get(t *testing.T, h http.Handler, token, path string) (int, string) {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

func workspace(t *testing.T) daemon.Paths {
	t.Helper()
	p := daemon.Paths{Workspace: t.TempDir()}
	if err := daemon.Prepare(p); err != nil {
		t.Fatal(err)
	}
	return p
}

func post(t *testing.T, h http.Handler, token, body string) int {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/event", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code
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
	h, l := server(t, clock.NewFake(time.Time{}))
	for _, ev := range []string{"session.start", "tool.call"} {
		body := fmt.Sprintf(`{"session":"s1","event":%q,"at":"t","e":{"x":1}}`, ev)
		if code := post(t, h, "tok", body); code != http.StatusOK {
			t.Fatalf("%s: status %d", ev, code)
		}
	}
	got := rows(t, l, "s1")
	if len(got) != 2 || got[0]["event"] != "session.start" || got[1]["event"] != "tool.call" {
		t.Fatalf("rows = %v", got)
	}
}

func TestAWrongTokenIsRefused(t *testing.T) {
	h, _ := server(t, clock.NewFake(time.Time{}))
	if code := post(t, h, "nope", `{"session":"s1","event":"x"}`); code != http.StatusUnauthorized {
		t.Fatalf("status %d", code)
	}
}

func TestASessionNameCannotLeaveTheLogFolder(t *testing.T) {
	h, _ := server(t, clock.NewFake(time.Time{}))
	for _, s := range []string{"../escape", "a/b", "", ".hidden"} {
		body := fmt.Sprintf(`{"session":%q,"event":"x"}`, s)
		if code := post(t, h, "tok", body); code != http.StatusBadRequest {
			t.Fatalf("session %q: status %d", s, code)
		}
	}
}

func TestALongPayloadLandsCut(t *testing.T) {
	h, l := server(t, clock.NewFake(time.Time{}))
	long := strings.Repeat("a", session.PayloadCap*2)
	post(t, h, "tok", fmt.Sprintf(`{"session":"s1","event":"x","e":%q}`, long))
	e := rows(t, l, "s1")[0]["e"].(map[string]any)
	if e["cut"] != true || int(e["length"].(float64)) != len(long)+2 {
		t.Fatalf("e = %v", e)
	}
}

func TestConcurrentEventsAllLand(t *testing.T) {
	h, l := server(t, clock.NewFake(time.Time{}))
	var wg sync.WaitGroup
	for i := range 50 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			post(t, h, "tok", fmt.Sprintf(`{"session":"s1","event":"e%d"}`, i))
		}()
	}
	wg.Wait()
	if n := len(rows(t, l, "s1")); n != 50 {
		t.Fatalf("%d rows", n)
	}
}

// Two posts alike are two events: each lands as the log module's input, and each is written.
func TestTwoEventsAlikeAreBothWritten(t *testing.T) {
	h, l := server(t, clock.NewFake(time.Time{}))
	for range 2 {
		post(t, h, "tok", `{"session":"s1","event":"x","at":"t"}`)
	}
	if n := len(rows(t, l, "s1")); n != 2 {
		t.Fatalf("%d rows", n)
	}
}

// The index the daemon hosts answers a name's value over the protocol: the
// clock's start, and the number of the last event the log wrote.
func TestTheDaemonAnswersValuesByName(t *testing.T) {
	at := time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)
	h, _ := server(t, clock.NewFake(at))
	value := func(name string) map[string]any {
		t.Helper()
		code, body := get(t, h, "tok", "/value/"+name)
		var v map[string]any
		if code != http.StatusOK || json.Unmarshal([]byte(body), &v) != nil {
			t.Fatalf("%s: status %d, %s", name, code, body)
		}
		return v
	}
	if v := value("clock/started"); v["value"] != at.Format(time.RFC3339) || v["provided"] != true {
		t.Fatalf("clock/started = %v", v)
	}
	if v := value("sessionlog/written"); v["value"] != float64(0) {
		t.Fatalf("sessionlog/written before any event = %v", v)
	}
	post(t, h, "tok", `{"session":"s1","event":"x"}`)
	post(t, h, "tok", `{"session":"s2","event":"y"}`)
	if v := value("sessionlog/written"); v["value"] != float64(2) || v["provided"] != true {
		t.Fatalf("sessionlog/written after two events = %v", v)
	}
	if code, _ := get(t, h, "tok", "/value/no/such"); code != http.StatusNotFound {
		t.Fatalf("a name nothing declares: status %d", code)
	}
	if code, _ := get(t, h, "nope", "/value/clock/started"); code != http.StatusUnauthorized {
		t.Fatalf("a wrong token: status %d", code)
	}
}

func TestServePublishesAndWithdrawsItsEndpoint(t *testing.T) {
	p := workspace(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, p, options(clock.Real(), session.NewFake(), func(ep daemon.Endpoint) { ready <- ep }))
	}()
	ep := <-ready
	if got, ok := daemon.Healthy(p); !ok || got.InstanceID != ep.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	if runtime.GOOS != "windows" {
		if err := daemon.Serve(context.Background(), p, options(clock.Real(), session.NewFake(), nil)); !errors.Is(err, daemon.ErrRunning) {
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
	p := workspace(t)
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), p, options(clock.Real(), session.NewFake(), func(ep daemon.Endpoint) { ready <- ep }))
	}()
	<-ready
	if err := daemon.Stop(p, 5*time.Second, clock.Real()); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if _, ok := daemon.Healthy(p); ok {
		t.Fatal("still healthy after stop")
	}
}

func TestAnIdleDaemonEnds(t *testing.T) {
	p := workspace(t)
	f := clock.NewFake(time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC))
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(context.Background(), p, idling(options(f, session.NewFake(), func(ep daemon.Endpoint) { ready <- ep })))
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
	p := workspace(t)
	first := make(chan daemon.Endpoint, 1)
	firstDone := make(chan error, 1)
	go func() {
		firstDone <- daemon.Serve(context.Background(), p, options(clock.Real(), session.NewFake(), func(ep daemon.Endpoint) { first <- ep }))
	}()
	ep1 := <-first
	ctx, cancel := context.WithCancel(context.Background())
	second := make(chan daemon.Endpoint, 1)
	secondDone := make(chan error, 1)
	go func() {
		secondDone <- daemon.Serve(ctx, p, withTakeOver(options(clock.Real(), session.NewFake(), func(ep daemon.Endpoint) { second <- ep })))
	}()
	ep2 := <-second
	if err := <-firstDone; err != nil {
		t.Fatal(err)
	}
	if got, ok := daemon.Healthy(p); !ok || got.InstanceID != ep2.InstanceID || ep2.InstanceID == ep1.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	cancel()
	if err := <-secondDone; err != nil {
		t.Fatal(err)
	}
}
