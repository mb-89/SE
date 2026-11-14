package mcp

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/host"
	"github.com/nats-io/nats.go"
)

// Core is the core as the door reaches it: the real one in the checkout
// (Host), or a test's fake.
type Core interface {
	// Start makes sure a core runs, and returns at once: running where one
	// does, else started or starting (host.Start).
	Start() (host.Started, error)
	// Status says whether the core runs, and its health (host.AskStatus).
	Status() (host.Status, error)
	// Lease takes or renews the session's lease, or returns it where end is
	// set (host.LeaseSubject).
	Lease(session string, end bool) error
	// Call runs a command through the core (call.<command>).
	Call(ctx context.Context, command string, args []string) (host.CallAnswer, error)
	// Get reads a name (get.<name>).
	Get(ctx context.Context, name string) (host.NameValue, error)
}

// Host is the real core in the checkout at Root, started as `<Bin> serve`
// with Args where none runs.
type Host struct {
	Root, Bin string
	Args      []string
}

func (h Host) Start() (host.Started, error) {
	return host.Start(host.Wall{}, h.Root, h.Bin, h.Args...)
}

func (h Host) Status() (host.Status, error) { return host.AskStatus(host.Wall{}, h.Root) }

func (h Host) dial() (*nats.Conn, error) {
	s, err := host.ReadStanding(h.Root)
	if err != nil {
		return nil, err
	}
	return bus.Dial(s.Bus, bus.Client, s.Users[bus.Client], nats.Timeout(host.HealthWait))
}

// request asks subject on the core's bus and reads the answer into v.
func (h Host) request(ctx context.Context, subject string, body, v any) error {
	nc, err := h.dial()
	if err != nil {
		return err
	}
	defer nc.Close()
	data, err := json.Marshal(body)
	if err != nil {
		return err
	}
	m, err := nc.RequestWithContext(ctx, subject, data)
	if err != nil {
		return fmt.Errorf("%s: %w", subject, err)
	}
	if err := json.Unmarshal(m.Data, v); err != nil {
		return fmt.Errorf("%s answers no JSON: %w", subject, err)
	}
	return nil
}

func (h Host) Lease(session string, end bool) error {
	ctx, cancel := context.WithTimeout(context.Background(), leaseWait)
	defer cancel()
	var got struct {
		Error string `json:"error"`
	}
	if err := h.request(ctx, host.LeaseSubject, host.Lease{Session: session, End: end}, &got); err != nil {
		return err
	}
	if got.Error != "" {
		return fmt.Errorf("%s", got.Error)
	}
	return nil
}

func (h Host) Call(ctx context.Context, command string, args []string) (host.CallAnswer, error) {
	if args == nil {
		args = []string{}
	}
	var a host.CallAnswer
	err := h.request(ctx, bus.Call+bus.Token(command), map[string]any{"args": args}, &a)
	return a, err
}

func (h Host) Get(ctx context.Context, name string) (host.NameValue, error) {
	var v host.NameValue
	err := h.request(ctx, bus.Get+bus.Subject(name), map[string]string{"name": name}, &v)
	return v, err
}
