// Package clock is the I/O module for time: the one place SE reads the wall
// clock, sleeps or waits. Code that needs time takes a Clock as an argument;
// the se binary hands it Real, a test hands it a Fake, so a case replays.
package clock

import "time"

// Clock is what SE asks of time.
type Clock interface {
	// Now answers the current time.
	Now() time.Time
	// Sleep returns once d has passed; d <= 0 returns at once.
	Sleep(d time.Duration)
	// After answers a channel that receives the time once d has passed.
	After(d time.Duration) <-chan time.Time
}

// Real answers the wall clock.
func Real() Clock { return wall{} }

type wall struct{}

func (wall) Now() time.Time                         { return time.Now() }
func (wall) Sleep(d time.Duration)                  { time.Sleep(d) }
func (wall) After(d time.Duration) <-chan time.Time { return time.After(d) }
