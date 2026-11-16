package mcp

import "time"

// The supervisor's decision, apart from carrying it out: Next and Refused
// read no clock, file or bus, so a table holds every row (step_test.go), and
// supervise only does what they say.

// CoreState is the core as the supervisor's last look found it.
type CoreState int

const (
	// CoreUnread: its status could not be read.
	CoreUnread CoreState = iota
	// CoreRunning: it runs and answers.
	CoreRunning
	// CoreStarting: a start's claim stands, or its bus does not answer yet.
	CoreStarting
	// CoreStopped: none runs, and none said why it ended.
	CoreStopped
	// CoreEnded: none runs, and the last one ended at its start, saying why
	// (host.Status.Died).
	CoreEnded
)

// Look is what the supervisor knows as it decides.
type Look struct {
	Core CoreState
	// Leased: the session's lease stands, taken or renewed by the last step.
	Leased bool
	// InFlight: the door's own start was made and no core has run since.
	InFlight bool
	// Asked: a call that found no core running ended the last wait.
	Asked bool
}

// Action is what a step does.
type Action int

const (
	// Wait does nothing but wait.
	Wait Action = iota
	// Lease takes or renews the session's lease.
	Lease
	// Start starts the core (Core.Start), the lease gone with the last one.
	Start
	// Fail says the core does not start: every call answers failed until a
	// core runs and the lease is taken.
	Fail
)

func (a Action) String() string {
	return [...]string{"wait", "lease", "start", "fail"}[a]
}

// Step is the supervisor's next step: its action, then the span to wait.
// Wake says whether a call's signal ends the wait early; a wait after Fail is
// never woken, so a core that cannot start is not spawned in a loop.
type Step struct {
	Do   Action
	Wait time.Duration
	Wake bool
}

// Spans are the supervisor's two waits: Look while a start is in flight,
// Renew between the lease's renewals.
type Spans struct {
	Look, Renew time.Duration
}

// Next is the step that follows look.
//
//   - unread: wait; Renew, or Look where a call asked, as it waits on the answer
//   - running: take or renew the lease, then wait Renew
//   - starting: wait Look
//   - ended, with the door's start in flight: fail, then wait Renew unwoken
//   - stopped, or ended before the door's start: start, then wait Look
//
// Leased changes no step: a running core's lease is renewed whether or not it
// stands. Every wait but the one after Fail ends on a call's signal, so a
// call that finds the core gone has it started at once.
func Next(l Look, s Spans) Step {
	switch l.Core {
	case CoreUnread:
		if l.Asked {
			return Step{Do: Wait, Wait: s.Look, Wake: true}
		}
		return Step{Do: Wait, Wait: s.Renew, Wake: true}
	case CoreRunning:
		return Step{Do: Lease, Wait: s.Renew, Wake: true}
	case CoreStarting:
		return Step{Do: Wait, Wait: s.Look, Wake: true}
	case CoreEnded:
		if l.InFlight {
			return Step{Do: Fail, Wait: s.Renew}
		}
	}
	return Step{Do: Start, Wait: s.Look, Wake: true}
}

// Refused is the step that follows an action that failed: a refused lease is
// asked again after Look; a start that fails is a failure, waited out unwoken
// for Renew.
func Refused(a Action, s Spans) Step {
	switch a {
	case Lease:
		return Step{Do: Wait, Wait: s.Look, Wake: true}
	case Start:
		return Step{Do: Fail, Wait: s.Renew}
	}
	return Next(Look{}, s)
}

// How the door came to its core, the status tool's "core".
const (
	Attached     = "attached"
	Started      = "started"
	StartedAgain = "started again"
)

// Came is how the door came to a core it now leases: spawned, by its own
// start; before, a core it reached earlier in its session.
func Came(spawned, before bool) string {
	switch {
	case !spawned:
		return Attached
	case before:
		return StartedAgain
	}
	return Started
}
