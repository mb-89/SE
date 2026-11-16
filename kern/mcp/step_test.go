package mcp

import (
	"fmt"
	"testing"
	"time"
)

// Next's table, every look: the rows of the supervisor before the wake
// (status unread, running, starting, ended at the door's start, stopped or
// ended before it) keep their steps, and every wait but the one after Fail
// ends on a call's signal.
func TestNextDecidesEveryLook(t *testing.T) {
	s := Spans{Look: time.Millisecond, Renew: time.Hour}
	wait := func(d time.Duration) Step { return Step{Do: Wait, Wait: d, Wake: true} }
	lease := Step{Do: Lease, Wait: s.Renew, Wake: true}
	start := Step{Do: Start, Wait: s.Look, Wake: true}
	fail := Step{Do: Fail, Wait: s.Renew}
	rows := []struct {
		core            CoreState
		inFlight, asked bool
		want            Step
	}{
		{CoreUnread, false, false, wait(s.Renew)},
		{CoreUnread, true, false, wait(s.Renew)},
		{CoreUnread, false, true, wait(s.Look)},
		{CoreUnread, true, true, wait(s.Look)},
		{CoreRunning, false, false, lease},
		{CoreRunning, true, false, lease},
		{CoreRunning, false, true, lease},
		{CoreRunning, true, true, lease},
		{CoreStarting, false, false, wait(s.Look)},
		{CoreStarting, true, false, wait(s.Look)},
		{CoreStarting, false, true, wait(s.Look)},
		{CoreStarting, true, true, wait(s.Look)},
		{CoreStopped, false, false, start},
		{CoreStopped, true, false, start},
		{CoreStopped, false, true, start},
		{CoreStopped, true, true, start},
		{CoreEnded, false, false, start},
		{CoreEnded, true, false, fail},
		{CoreEnded, false, true, start},
		{CoreEnded, true, true, fail},
	}
	for _, r := range rows {
		for _, leased := range []bool{false, true} {
			l := Look{Core: r.core, Leased: leased, InFlight: r.inFlight, Asked: r.asked}
			if got := Next(l, s); got != r.want {
				t.Errorf("Next(%+v) is %s, and wants %s", l, show(got), show(r.want))
			}
		}
	}
}

// A refused lease is asked again after Look; a start that fails is a
// failure, waited out unwoken.
func TestRefusedFollowsAFailedAction(t *testing.T) {
	s := Spans{Look: time.Millisecond, Renew: time.Hour}
	if got := Refused(Lease, s); got != (Step{Do: Wait, Wait: s.Look, Wake: true}) {
		t.Errorf("a refused lease is followed by %s, and wants a wait of Look", show(got))
	}
	if got := Refused(Start, s); got != (Step{Do: Fail, Wait: s.Renew}) {
		t.Errorf("a failed start is followed by %s, and wants fail, then Renew unwoken", show(got))
	}
}

func TestCameNamesHowTheDoorReachedItsCore(t *testing.T) {
	for _, c := range []struct {
		spawned, before bool
		want            string
	}{{false, false, Attached}, {false, true, Attached}, {true, false, Started}, {true, true, StartedAgain}} {
		if got := Came(c.spawned, c.before); got != c.want {
			t.Errorf("Came(%v, %v) is %q, and wants %q", c.spawned, c.before, got, c.want)
		}
	}
}

func show(s Step) string { return fmt.Sprintf("%s for %v (woken: %v)", s.Do, s.Wait, s.Wake) }
