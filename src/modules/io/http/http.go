// Package http is the I/O module for the network: the one place SE serves or
// calls over HTTP. It speaks two things and nothing more: the daemon protocol
// the plugin's bridgehead and the se command line post to (health, event,
// value, command, shutdown), served and called from Go, and the routine's API
// trigger, the fire. Code that needs the network takes a Net as an argument;
// the se binary hands it Real, a test hands it a Fake, so a case replays.
package http

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
)

// Net is what SE asks of the network.
type Net interface {
	// Serve answers the daemon protocol for d on a loopback address, behind
	// token, until ctx ends. It answers the address, and a channel that
	// receives once serving has ended: nil after ctx ended, else why it failed.
	Serve(ctx context.Context, token string, d Daemon) (address string, done <-chan error, err error)
	// Health asks the daemon at address how it stands.
	Health(address, token string) (Health, error)
	// Event posts one session event to the daemon at address.
	Event(address, token string, ev Event) error
	// Value asks the daemon at address for name's value on its index.
	Value(address, token, name string) (Value, error)
	// Command asks the daemon at address to run a command of its index and
	// answers its reply. It waits as long as the command runs.
	Command(address, token string, c CommandCall) (Reply, error)
	// Shutdown asks the daemon at address to end.
	Shutdown(address, token string) error
	// Fire posts once to the routine's API trigger at url and answers what it said.
	Fire(url, token string) (Answer, error)
}

// Daemon is what a served daemon answers; Serve calls it for each post whose
// token holds.
type Daemon interface {
	// Health is the daemon's answer to /health.
	Health() Health
	// Event takes one session event. An error that wraps ErrBad refuses the
	// event as malformed; any other says the daemon failed to keep it.
	Event(Event) error
	// Value answers name's value. An error that wraps ErrUnknown says
	// nothing declares the name.
	Value(name string) (Value, error)
	// Command runs a command of the daemon's index and answers its reply. An
	// error that wraps ErrUnknown says nothing declares the command; any
	// other is why the command failed.
	Command(CommandCall) (Reply, error)
	// Shutdown asks the daemon to end; it is called once /shutdown is answered.
	Shutdown()
}

// Health is how a daemon says it stands.
type Health struct {
	ProtocolVersion int    `json:"protocolVersion"`
	InstanceID      string `json:"instanceId"`
	PID             int    `json:"pid"`
}

// Event is one post of the bridgehead: a session event as the engine raised it.
type Event struct {
	Session string          `json:"session"`
	Event   string          `json:"event"`
	At      string          `json:"at"`
	E       json.RawMessage `json:"e"`
}

// Value is a name's value on a daemon's index, and whether anything provided it.
type Value struct {
	Value    any  `json:"value"`
	Provided bool `json:"provided"`
}

// CommandCall is one call of a command on a daemon's index: the command's
// name, such as "issue land", and the words after it, flags and all.
type CommandCall struct {
	Name  string   `json:"name"`
	Words []string `json:"words"`
}

// Reply is what a command run on a daemon answers: its text, or its data as
// JSON where the call said --json.
type Reply struct {
	Text string `json:"text"`
}

// Answer is what the routine's trigger said to a fire.
type Answer struct {
	// Status is the HTTP status code.
	Status int
	// Body is the answer's body, cut at BodyCap.
	Body []byte
	// RetryAfter is the answer's Retry-After header, as it came: seconds, or
	// an HTTP date. A routine's 429 names in it when its limit resets.
	RetryAfter string
}

// OK says the fire was taken: a 2xx status.
func (a Answer) OK() bool { return a.Status/100 == 2 }

// ErrBad marks a post the daemon refuses as malformed.
var ErrBad = errors.New("bad request")

// ErrUnknown marks a name or a command the daemon's index does not declare.
var ErrUnknown = errors.New("unknown name")

// commandStatus is the status a failed command answers with: not found for
// a command the index does not declare, an internal error for any other.
func commandStatus(err error) int {
	if errors.Is(err, ErrUnknown) {
		return StatusNotFound
	}
	return StatusInternal
}

// StatusError is a daemon's refusal: a post it answered with a status other than 200.
type StatusError struct {
	Path   string
	Status int
	Said   string
}

func (e *StatusError) Error() string {
	return fmt.Sprintf("%s: status %d: %s", e.Path, e.Status, e.Said)
}

// The caps on what one post carries.
const (
	// EventCap bounds one event post.
	EventCap = 16 << 20
	// BodyCap bounds the part of an answer Fire keeps.
	BodyCap = 64 << 10
)

// Status codes the daemon protocol answers with.
const (
	StatusOK           = 200
	StatusBadRequest   = 400
	StatusUnauthorized = 401
	StatusNotFound     = 404
	StatusInternal     = 500
	StatusTooMany      = 429
)

// Routine trigger headers: what every fire carries besides its token.
const (
	routineBeta    = "experimental-cc-routine-2026-04-01"
	routineVersion = "2023-06-01"
)
