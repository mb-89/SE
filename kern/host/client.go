package host

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/nats-io/nats.go"
)

// The waits of a client: the health's, as the greeting's (docs/go-core.md,
// "The start budget"), and a stop's.
const (
	HealthWait = 200 * time.Millisecond
	stopWait   = 2 * time.Second
	exitWait   = 10 * time.Second
	exitLook   = 5 * time.Millisecond
)

// State is what a status finds.
type State string

const (
	StateRunning  State = "running"
	StateStarting State = "starting"
	StateStopped  State = "not running"
)

// Status is a core's state, and its health where it answers; where none runs,
// what the last one said as it ended at its start (ReadDied), if it did.
type Status struct {
	State  State
	Health Health
	Died   string
}

// AskStatus asks the core in the checkout at root for its health. Where none
// answers, a claim younger than ClaimStale or a standing file whose bus does
// not answer yet reads as starting.
func AskStatus(clock Clock, root string) (Status, error) {
	s, err := ReadStanding(root)
	if err != nil {
		if !errors.Is(err, ErrNotRunning) {
			return Status{}, err
		}
		if st, err := os.Stat(ClaimPath(root)); err == nil && clock.Now().Sub(st.ModTime()) <= ClaimStale {
			return Status{State: StateStarting}, nil
		}
		return Status{State: StateStopped, Died: ReadDied(root)}, nil
	}
	h, err := health(s)
	if err != nil {
		return Status{State: StateStarting}, nil
	}
	return Status{State: StateRunning, Health: h}, nil
}

func health(s Standing) (Health, error) {
	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		return Health{}, err
	}
	defer nc.Close()
	m, err := nc.Request(HealthSubject, nil, HealthWait)
	if err != nil {
		return Health{}, fmt.Errorf("kern status: %s: %w", HealthSubject, err)
	}
	var h Health
	if err := json.Unmarshal(m.Data, &h); err != nil {
		return Health{}, fmt.Errorf("kern status: %s answers no health: %w", HealthSubject, err)
	}
	return h, nil
}

// AskStop stops the core in the checkout at root and waits until its process
// has exited, so the caller meets no running core after it, and Windows lets
// the checkout's folders go. Where the core does not answer, its process is
// killed. It answers the pid stopped, or zero where none ran.
func AskStop(root string) (int, error) {
	s, err := ReadStanding(root)
	if errors.Is(err, ErrNotRunning) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	asked := false
	if nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client]); err == nil {
		_, err = nc.Request(StopSubject, nil, stopWait)
		// A core that goes down before its answer reaches the caller was asked all the same.
		asked = err == nil || errors.Is(err, nats.ErrConnectionClosed)
		nc.Close()
	}
	if !asked {
		if p, err := os.FindProcess(s.Pid); err == nil {
			_ = p.Kill()
		}
	}
	end := time.Now().Add(exitWait)
	for alive(s.Pid) {
		if time.Now().After(end) {
			return s.Pid, fmt.Errorf("kern stop: pid %d still runs %v after the stop", s.Pid, exitWait)
		}
		time.Sleep(exitLook)
	}
	if !asked {
		dropStanding(root, s.Pid)
	}
	return s.Pid, nil
}

// WaitRunning asks the status until the core answers, it ended at its start,
// or the wait is out.
func WaitRunning(clock Clock, root string, wait time.Duration) (Status, error) {
	end := time.Now().Add(wait)
	for {
		st, err := AskStatus(clock, root)
		if err != nil || st.State == StateRunning || st.Died != "" || !time.Now().Before(end) {
			return st, err
		}
		time.Sleep(time.Millisecond)
	}
}
