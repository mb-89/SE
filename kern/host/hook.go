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

// HookWait is how long a hook waits for the core, a start in progress
// included: SE's docs/go-core.md ("Nobody starts the index by hand").
const HookWait = 500 * time.Millisecond

// standingLook is how often a hook looks for the standing file of a core
// that is starting.
const standingLook = 2 * time.Millisecond

// ErrNoEvent is what Post answers for an event name that is no single word.
var ErrNoEvent = errors.New("a hook event is one word of letters")

// Post sends a host's hook event, its JSON as the host gave it, on
// hook.<event> to the core in the checkout at root, and answers the core's
// effect. Where a start's claim stands but the standing file does not yet,
// it waits for the core within wait; where no core runs and none is
// starting, it answers ErrNotRunning at once. A hook fails open on every
// error: the caller prints nothing.
func Post(clock Clock, root, event string, payload []byte, wait time.Duration) (HookAnswer, error) {
	if !word(event) {
		return HookAnswer{}, fmt.Errorf("kern hook %q: %w", event, ErrNoEvent)
	}
	end := time.Now().Add(wait)
	s, err := ReadStanding(root)
	for errors.Is(err, ErrNotRunning) && starting(clock, root) && time.Now().Before(end) {
		time.Sleep(standingLook)
		s, err = ReadStanding(root)
	}
	if err != nil {
		return HookAnswer{}, err
	}
	left := time.Until(end)
	if left <= 0 {
		return HookAnswer{}, fmt.Errorf("kern hook %s: no answer within %v", event, wait)
	}
	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client], nats.Timeout(left))
	if err != nil {
		return HookAnswer{}, err
	}
	defer nc.Close()
	m, err := nc.Request(bus.Hook+event, payload, time.Until(end))
	if err != nil {
		return HookAnswer{}, fmt.Errorf("kern hook %s: %w", event, err)
	}
	var a HookAnswer
	if err := json.Unmarshal(m.Data, &a); err != nil {
		return HookAnswer{}, fmt.Errorf("kern hook %s answers no effect: %w", event, err)
	}
	return a, nil
}

// starting says whether a start's claim stands that is younger than ClaimStale.
func starting(clock Clock, root string) bool {
	st, err := os.Stat(ClaimPath(root))
	return err == nil && clock.Now().Sub(st.ModTime()) <= ClaimStale
}

func word(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if (r < 'A' || r > 'Z') && (r < 'a' || r > 'z') {
			return false
		}
	}
	return true
}
