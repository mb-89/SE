package http

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"sync"
)

// Fake is a network inside the process: a daemon served on it answers at an
// address of its own, behind its token, until its context ends; a routine
// trigger stood up on it takes fires with its token until its limit is spent.
// Nothing leaves the process, and every answer comes from the fake's state.
type Fake struct {
	mu       sync.Mutex
	port     int
	served   map[string]served
	routines map[string]*routine
	sessions int
}

type served struct {
	token string
	d     Daemon
}

type routine struct {
	token string
	left  int
	fired int
}

// NewFake answers an empty fake network: nothing is served, no routine stands.
func NewFake() *Fake {
	return &Fake{port: 40000, served: map[string]served{}, routines: map[string]*routine{}}
}

// Routine stands up a routine's trigger at url that takes token and answers
// limit fires, then refuses as rate limited.
func (f *Fake) Routine(url, token string, limit int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.routines[url] = &routine{token: token, left: limit}
}

// Fired answers how many fires the routine at url has taken.
func (f *Fake) Fired(url string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	if r, ok := f.routines[url]; ok {
		return r.fired
	}
	return 0
}

func (f *Fake) Serve(ctx context.Context, token string, d Daemon) (string, <-chan error, error) {
	f.mu.Lock()
	f.port++
	address := fmt.Sprintf("127.0.0.1:%d", f.port)
	f.served[address] = served{token: token, d: d}
	f.mu.Unlock()
	done := make(chan error, 1)
	go func() {
		<-ctx.Done()
		f.mu.Lock()
		delete(f.served, address)
		f.mu.Unlock()
		done <- nil
	}()
	return address, done, nil
}

// reach answers the daemon at address once its token holds.
func (f *Fake) reach(address, token, path string) (Daemon, error) {
	f.mu.Lock()
	s, ok := f.served[address]
	f.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("dial tcp %s: connect: connection refused", address)
	}
	if s.token != token {
		return nil, &StatusError{Path: path, Status: StatusUnauthorized, Said: "unauthorized"}
	}
	return s.d, nil
}

func (f *Fake) Health(address, token string) (Health, error) {
	d, err := f.reach(address, token, "/health")
	if err != nil {
		return Health{}, err
	}
	// The answer crosses the wire as JSON, as the real one does.
	var h Health
	err = roundTrip(d.Health(), &h)
	return h, err
}

func (f *Fake) Event(address, token string, ev Event) error {
	body, err := json.Marshal(ev)
	if err != nil {
		return err
	}
	d, err := f.reach(address, token, "/event")
	if err != nil {
		return err
	}
	var got Event
	if len(body) > EventCap {
		return &StatusError{Path: "/event", Status: StatusBadRequest, Said: "bad event: http: request body too large"}
	}
	if err := json.Unmarshal(body, &got); err != nil {
		return &StatusError{Path: "/event", Status: StatusBadRequest, Said: "bad event: " + err.Error()}
	}
	if err := d.Event(got); err != nil {
		code := StatusInternal
		if errors.Is(err, ErrBad) {
			code = StatusBadRequest
		}
		return &StatusError{Path: "/event", Status: code, Said: err.Error()}
	}
	return nil
}

func (f *Fake) Value(address, token, name string) (Value, error) {
	path := "/value/" + name
	d, err := f.reach(address, token, path)
	if err != nil {
		return Value{}, err
	}
	v, err := d.Value(name)
	if err != nil {
		code := StatusInternal
		if errors.Is(err, ErrUnknown) {
			code = StatusNotFound
		}
		return Value{}, &StatusError{Path: path, Status: code, Said: err.Error()}
	}
	var got Value
	err = roundTrip(v, &got)
	return got, err
}

func (f *Fake) Shutdown(address, token string) error {
	d, err := f.reach(address, token, "/shutdown")
	if err != nil {
		return err
	}
	go d.Shutdown()
	return nil
}

func (f *Fake) Fire(to, token string) (Answer, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.routines[to]
	switch {
	case !ok:
		// The error reads as the real client's does: it names the url.
		return Answer{}, &url.Error{Op: "Post", URL: to, Err: errors.New("dial tcp: connect: connection refused")}
	case r.token != token:
		return Answer{Status: StatusUnauthorized, Body: []byte(`{"type":"error","error":{"type":"authentication_error","message":"invalid bearer token"}}`)}, nil
	case r.left <= 0:
		return Answer{Status: StatusTooMany, Body: []byte(`{"type":"error","error":{"type":"rate_limit_error","message":"the routine's fires are spent"}}`)}, nil
	}
	r.left--
	r.fired++
	f.sessions++
	id := fmt.Sprintf("session_fake%d", f.sessions)
	body, err := json.Marshal(map[string]string{
		"type":                    "routine_fire",
		"claude_code_session_id":  id,
		"claude_code_session_url": "https://claude.ai/code/" + id,
	})
	return Answer{Status: StatusOK, Body: body}, err
}

func roundTrip(v, into any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, into)
}
