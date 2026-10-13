package daemon

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
)

func workspace(t *testing.T) Paths {
	t.Helper()
	p := Paths{Workspace: t.TempDir()}
	if err := Prepare(p); err != nil {
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

func rows(t *testing.T, p Paths, session string) []map[string]any {
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
	h := NewServer(p, "tok", "i1", nil).Handler()
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
	h := NewServer(p, "tok", "i1", nil).Handler()
	if code := post(t, h, "nope", `{"session":"s1","event":"x"}`); code != http.StatusUnauthorized {
		t.Fatalf("status %d", code)
	}
}

func TestASessionNameCannotLeaveTheLogFolder(t *testing.T) {
	p := workspace(t)
	h := NewServer(p, "tok", "i1", nil).Handler()
	for _, s := range []string{"../escape", "a/b", "", ".hidden"} {
		body := fmt.Sprintf(`{"session":%q,"event":"x"}`, s)
		if code := post(t, h, "tok", body); code != http.StatusBadRequest {
			t.Fatalf("session %q: status %d", s, code)
		}
	}
}

func TestALongPayloadLandsCut(t *testing.T) {
	p := workspace(t)
	h := NewServer(p, "tok", "i1", nil).Handler()
	long := strings.Repeat("a", PayloadCap*2)
	post(t, h, "tok", fmt.Sprintf(`{"session":"s1","event":"x","e":%q}`, long))
	e := rows(t, p, "s1")[0]["e"].(map[string]any)
	if e["cut"] != true || int(e["length"].(float64)) != len(long)+2 {
		t.Fatalf("e = %v", e)
	}
}

func TestConcurrentEventsAllLand(t *testing.T) {
	p := workspace(t)
	h := NewServer(p, "tok", "i1", nil).Handler()
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
	ready := make(chan Endpoint, 1)
	go func() { done <- Serve(ctx, p, Options{Ready: func(ep Endpoint) { ready <- ep }}) }()
	ep := <-ready
	if got, ok := Healthy(p); !ok || got.InstanceID != ep.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	if runtime.GOOS != "windows" {
		if err := Serve(context.Background(), p, Options{}); !errors.Is(err, ErrRunning) {
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
	ready := make(chan Endpoint, 1)
	go func() {
		done <- Serve(context.Background(), p, Options{Ready: func(ep Endpoint) { ready <- ep }})
	}()
	<-ready
	if err := Stop(p, 5*time.Second); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if _, ok := Healthy(p); ok {
		t.Fatal("still healthy after stop")
	}
}

func TestAnIdleDaemonEnds(t *testing.T) {
	p := workspace(t)
	done := make(chan error, 1)
	go func() { done <- Serve(context.Background(), p, Options{Idle: 200 * time.Millisecond}) }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the daemon did not idle out")
	}
}

func TestTakeOverStepsARunningDaemonAside(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the lock is not exclusive here")
	}
	p := workspace(t)
	first := make(chan Endpoint, 1)
	firstDone := make(chan error, 1)
	go func() {
		firstDone <- Serve(context.Background(), p, Options{Ready: func(ep Endpoint) { first <- ep }})
	}()
	ep1 := <-first
	ctx, cancel := context.WithCancel(context.Background())
	second := make(chan Endpoint, 1)
	secondDone := make(chan error, 1)
	go func() {
		secondDone <- Serve(ctx, p, Options{TakeOver: 10 * time.Second, Ready: func(ep Endpoint) { second <- ep }})
	}()
	ep2 := <-second
	if err := <-firstDone; err != nil {
		t.Fatal(err)
	}
	if got, ok := Healthy(p); !ok || got.InstanceID != ep2.InstanceID || ep2.InstanceID == ep1.InstanceID {
		t.Fatalf("healthy = %v, %v", got, ok)
	}
	cancel()
	if err := <-secondDone; err != nil {
		t.Fatal(err)
	}
}
