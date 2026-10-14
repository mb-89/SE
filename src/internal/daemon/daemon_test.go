package daemon_test

import (
	"bufio"
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

	"github.com/mb-89/SE/src/internal/io/clock"

	"github.com/mb-89/SE/src/internal/daemon"
)

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

func rows(t *testing.T, p daemon.Paths, session string) []map[string]any {
	t.Helper()
	f, err := os.Open(filepath.Join(p.Logs(), session+".jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out []map[string]any
	sc := bufio.NewScanner(f)
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
	p := workspace(t)
	h := daemon.NewServer(p, "tok", "i1", nil, clock.NewFake(time.Time{})).Handler()
	for _, ev := range []string{"session.start", "tool.call"} {
		body := fmt.Sprintf(`{"session":"s1","event":%q,"at":"t","e":{"x":1}}`, ev)
		if code := post(t, h, "tok", body); code != http.StatusOK {
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
	h := daemon.NewServer(p, "tok", "i1", nil, clock.NewFake(time.Time{})).Handler()
	if code := post(t, h, "nope", `{"session":"s1","event":"x"}`); code != http.StatusUnauthorized {
		t.Fatalf("status %d", code)
	}
}

func TestASessionNameCannotLeaveTheLogFolder(t *testing.T) {
	p := workspace(t)
	h := daemon.NewServer(p, "tok", "i1", nil, clock.NewFake(time.Time{})).Handler()
	for _, s := range []string{"../escape", "a/b", "", ".hidden"} {
		body := fmt.Sprintf(`{"session":%q,"event":"x"}`, s)
		if code := post(t, h, "tok", body); code != http.StatusBadRequest {
			t.Fatalf("session %q: status %d", s, code)
		}
	}
}

func TestALongPayloadLandsCut(t *testing.T) {
	p := workspace(t)
	h := daemon.NewServer(p, "tok", "i1", nil, clock.NewFake(time.Time{})).Handler()
	long := strings.Repeat("a", daemon.PayloadCap*2)
	post(t, h, "tok", fmt.Sprintf(`{"session":"s1","event":"x","e":%q}`, long))
	e := rows(t, p, "s1")[0]["e"].(map[string]any)
	if e["cut"] != true || int(e["length"].(float64)) != len(long)+2 {
		t.Fatalf("e = %v", e)
	}
}

func TestConcurrentEventsAllLand(t *testing.T) {
	p := workspace(t)
	h := daemon.NewServer(p, "tok", "i1", nil, clock.NewFake(time.Time{})).Handler()
	var wg sync.WaitGroup
	for i := range 50 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			post(t, h, "tok", fmt.Sprintf(`{"session":"s1","event":"e%d"}`, i))
		}()
	}
	wg.Wait()
	if n := len(rows(t, p, "s1")); n != 50 {
		t.Fatalf("%d rows", n)
	}
}

func TestServePublishesAndWithdrawsItsEndpoint(t *testing.T) {
	p := workspace(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, p, daemon.Options{Clock: clock.Real(), Ready: func(ep daemon.Endpoint) { ready <- ep }})
	}()
	ep := <-ready
	if got, ok := daemon.Healthy(p); !ok || got.InstanceID != ep.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	if runtime.GOOS != "windows" {
		if err := daemon.Serve(context.Background(), p, daemon.Options{Clock: clock.Real()}); !errors.Is(err, daemon.ErrRunning) {
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
		done <- daemon.Serve(context.Background(), p, daemon.Options{Clock: clock.Real(), Ready: func(ep daemon.Endpoint) { ready <- ep }})
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
		done <- daemon.Serve(context.Background(), p, daemon.Options{Idle: 30 * time.Minute, Clock: f, Ready: func(ep daemon.Endpoint) { ready <- ep }})
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
		firstDone <- daemon.Serve(context.Background(), p, daemon.Options{Clock: clock.Real(), Ready: func(ep daemon.Endpoint) { first <- ep }})
	}()
	ep1 := <-first
	ctx, cancel := context.WithCancel(context.Background())
	second := make(chan daemon.Endpoint, 1)
	secondDone := make(chan error, 1)
	go func() {
		secondDone <- daemon.Serve(ctx, p, daemon.Options{Clock: clock.Real(), TakeOver: 10 * time.Second, Ready: func(ep daemon.Endpoint) { second <- ep }})
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
