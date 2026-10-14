package http_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"

	sehttp "github.com/mb-89/SE/src/internal/io/http"
)

// world is one fresh network for a contract case, and a way to stand up a
// routine trigger on it that takes token and answers limit fires.
type world struct {
	net     sehttp.Net
	routine func(token string, limit int) (url string, fired func() int)
}

// daemon is a Daemon that keeps what it is told: it refuses the session "bad"
// as malformed and fails to keep the session "broken". Its one value,
// events/kept, is how many events it kept.
type daemon struct {
	mu     sync.Mutex
	events []sehttp.Event
	ended  chan struct{}
	once   sync.Once
}

func newDaemon() *daemon { return &daemon{ended: make(chan struct{})} }

func (d *daemon) Health() sehttp.Health {
	return sehttp.Health{ProtocolVersion: 7, InstanceID: "i1", PID: 42}
}

func (d *daemon) Event(ev sehttp.Event) error {
	switch ev.Session {
	case "bad":
		return fmt.Errorf("%w: no such session", sehttp.ErrBad)
	case "broken":
		return errors.New("the disk is full")
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.events = append(d.events, ev)
	return nil
}

func (d *daemon) Value(name string) (sehttp.Value, error) {
	if name != "events/kept" {
		return sehttp.Value{}, fmt.Errorf("%w: %s", sehttp.ErrUnknown, name)
	}
	return sehttp.Value{Value: len(d.kept()), Provided: true}, nil
}

func (d *daemon) Shutdown() { d.once.Do(func() { close(d.ended) }) }

func (d *daemon) kept() []sehttp.Event {
	d.mu.Lock()
	defer d.mu.Unlock()
	return append([]sehttp.Event(nil), d.events...)
}

// serve serves a fresh daemon on n behind "tok" until the case ends.
func serve(t *testing.T, n sehttp.Net) (*daemon, string) {
	t.Helper()
	d := newDaemon()
	ctx, cancel := context.WithCancel(context.Background())
	addr, done, err := n.Serve(ctx, "tok", d)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); <-done })
	return d, addr
}

func status(err error) int {
	var s *sehttp.StatusError
	if errors.As(err, &s) {
		return s.Status
	}
	return 0
}

// contract is the one suite every Net keeps, the fake as the real one. fresh
// answers a new world for each case.
func contract(t *testing.T, fresh func(t *testing.T) world) {
	t.Run("health answers what the daemon says", func(t *testing.T) {
		w := fresh(t)
		_, addr := serve(t, w.net)
		h, err := w.net.Health(addr, "tok")
		if err != nil || h != (sehttp.Health{ProtocolVersion: 7, InstanceID: "i1", PID: 42}) {
			t.Fatalf("health = %+v, %v", h, err)
		}
	})
	t.Run("a wrong token is refused and reaches nothing", func(t *testing.T) {
		w := fresh(t)
		d, addr := serve(t, w.net)
		if _, err := w.net.Health(addr, "nope"); status(err) != sehttp.StatusUnauthorized {
			t.Fatalf("health: %v", err)
		}
		if err := w.net.Event(addr, "nope", sehttp.Event{Session: "s1", Event: "x"}); status(err) != sehttp.StatusUnauthorized {
			t.Fatalf("event: %v", err)
		}
		if _, err := w.net.Value(addr, "nope", "events/kept"); status(err) != sehttp.StatusUnauthorized {
			t.Fatalf("value: %v", err)
		}
		if err := w.net.Shutdown(addr, ""); status(err) != sehttp.StatusUnauthorized {
			t.Fatalf("shutdown: %v", err)
		}
		if len(d.kept()) != 0 {
			t.Fatalf("the daemon kept %v", d.kept())
		}
		select {
		case <-d.ended:
			t.Fatal("the daemon was shut down")
		default:
		}
	})
	t.Run("an event arrives whole", func(t *testing.T) {
		w := fresh(t)
		d, addr := serve(t, w.net)
		ev := sehttp.Event{Session: "s1", Event: "tool.call", At: "2026-10-14T12:00:00Z", E: json.RawMessage(`{"x":[1,"two"]}`)}
		if err := w.net.Event(addr, "tok", ev); err != nil {
			t.Fatal(err)
		}
		got := d.kept()
		if len(got) != 1 || got[0].Session != ev.Session || got[0].Event != ev.Event || got[0].At != ev.At || string(got[0].E) != string(ev.E) {
			t.Fatalf("kept %+v", got)
		}
	})
	t.Run("an event without a payload arrives with none", func(t *testing.T) {
		w := fresh(t)
		d, addr := serve(t, w.net)
		if err := w.net.Event(addr, "tok", sehttp.Event{Session: "s1", Event: "x"}); err != nil {
			t.Fatal(err)
		}
		if got := d.kept(); len(got) != 1 || (len(got[0].E) != 0 && string(got[0].E) != "null") {
			t.Fatalf("kept %+v", got)
		}
	})
	t.Run("a refused event is a bad request, a failed one an internal error", func(t *testing.T) {
		w := fresh(t)
		_, addr := serve(t, w.net)
		err := w.net.Event(addr, "tok", sehttp.Event{Session: "bad", Event: "x"})
		if status(err) != sehttp.StatusBadRequest || !strings.Contains(err.Error(), "no such session") {
			t.Fatalf("refused: %v", err)
		}
		err = w.net.Event(addr, "tok", sehttp.Event{Session: "broken", Event: "x"})
		if status(err) != sehttp.StatusInternal || !strings.Contains(err.Error(), "the disk is full") {
			t.Fatalf("failed: %v", err)
		}
	})
	t.Run("concurrent events all arrive", func(t *testing.T) {
		w := fresh(t)
		d, addr := serve(t, w.net)
		var wg sync.WaitGroup
		for i := range 20 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if err := w.net.Event(addr, "tok", sehttp.Event{Session: "s1", Event: fmt.Sprintf("e%d", i)}); err != nil {
					t.Error(err)
				}
			}()
		}
		wg.Wait()
		if n := len(d.kept()); n != 20 {
			t.Fatalf("%d events arrived", n)
		}
	})
	t.Run("a value answers by its name, an unknown name is not found", func(t *testing.T) {
		w := fresh(t)
		_, addr := serve(t, w.net)
		if err := w.net.Event(addr, "tok", sehttp.Event{Session: "s1", Event: "x"}); err != nil {
			t.Fatal(err)
		}
		v, err := w.net.Value(addr, "tok", "events/kept")
		if err != nil || v.Value != float64(1) || !v.Provided {
			t.Fatalf("events/kept = %+v, %v", v, err)
		}
		if _, err := w.net.Value(addr, "tok", "no/such"); status(err) != sehttp.StatusNotFound || !strings.Contains(err.Error(), "no/such") {
			t.Fatalf("no/such: %v", err)
		}
	})
	t.Run("shutdown reaches the daemon", func(t *testing.T) {
		w := fresh(t)
		d, addr := serve(t, w.net)
		if err := w.net.Shutdown(addr, "tok"); err != nil {
			t.Fatal(err)
		}
		<-d.ended
	})
	t.Run("two daemons answer apart", func(t *testing.T) {
		w := fresh(t)
		d1, a1 := serve(t, w.net)
		d2, a2 := serve(t, w.net)
		if a1 == a2 {
			t.Fatalf("both at %s", a1)
		}
		if err := w.net.Event(a2, "tok", sehttp.Event{Session: "s2", Event: "x"}); err != nil {
			t.Fatal(err)
		}
		if len(d1.kept()) != 0 || len(d2.kept()) != 1 {
			t.Fatalf("kept %v and %v", d1.kept(), d2.kept())
		}
	})
	t.Run("once its context ends, serving ends and nothing answers", func(t *testing.T) {
		w := fresh(t)
		ctx, cancel := context.WithCancel(context.Background())
		addr, done, err := w.net.Serve(ctx, "tok", newDaemon())
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.net.Health(addr, "tok"); err != nil {
			t.Fatal(err)
		}
		cancel()
		if err := <-done; err != nil {
			t.Fatalf("serving ended with %v", err)
		}
		if _, err := w.net.Health(addr, "tok"); err == nil || status(err) != 0 {
			t.Fatalf("health after the end: %v", err)
		}
		if err := w.net.Event(addr, "tok", sehttp.Event{Session: "s1", Event: "x"}); err == nil {
			t.Fatal("an event was taken after the end")
		}
	})
	t.Run("a fire with the token is taken and names its session", func(t *testing.T) {
		w := fresh(t)
		url, fired := w.routine("sekrit", 3)
		a, err := w.net.Fire(url, "sekrit")
		if err != nil || !a.OK() || fired() != 1 {
			t.Fatalf("fire = %d %s, %v; %d fired", a.Status, a.Body, err, fired())
		}
		var said map[string]any
		if err := json.Unmarshal(a.Body, &said); err != nil || !strings.HasPrefix(fmt.Sprint(said["claude_code_session_url"]), "https://") {
			t.Fatalf("answer %s: %v", a.Body, err)
		}
	})
	t.Run("a fire with a wrong token is refused and not taken", func(t *testing.T) {
		w := fresh(t)
		url, fired := w.routine("sekrit", 3)
		a, err := w.net.Fire(url, "nope")
		if err != nil || a.Status != sehttp.StatusUnauthorized || a.OK() || fired() != 0 {
			t.Fatalf("fire = %d %s, %v; %d fired", a.Status, a.Body, err, fired())
		}
	})
	t.Run("a fire past the routine's limit is rate limited", func(t *testing.T) {
		w := fresh(t)
		url, fired := w.routine("sekrit", 1)
		if a, err := w.net.Fire(url, "sekrit"); err != nil || !a.OK() {
			t.Fatalf("first fire = %d, %v", a.Status, err)
		}
		a, err := w.net.Fire(url, "sekrit")
		if err != nil || a.Status != sehttp.StatusTooMany || a.RetryAfter != "1800" || fired() != 1 {
			t.Fatalf("second fire = %d %s, %v; %d fired", a.Status, a.Body, err, fired())
		}
	})
	t.Run("a fire where no routine stands fails", func(t *testing.T) {
		w := fresh(t)
		w.routine("sekrit", 1)
		// Port 1 is never listened on, and no routine stands there.
		gone := "http://127.0.0.1:1/fire"
		if a, err := w.net.Fire(gone, "sekrit"); err == nil {
			t.Fatalf("fire = %d %s", a.Status, a.Body)
		}
	})
}
