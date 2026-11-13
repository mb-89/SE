package host

import "time"

// Clock is the time the core reads and waits on. The core's own process
// hands in the wall clock; a test hands in a clock it moves itself.
type Clock interface {
	Now() time.Time
	After(d time.Duration) <-chan time.Time
}

// Wall is the system's clock.
type Wall struct{}

func (Wall) Now() time.Time                         { return time.Now() }
func (Wall) After(d time.Duration) <-chan time.Time { return time.After(d) }
