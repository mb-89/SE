package clock

import (
	"time"

	"github.com/mb-89/SE/src/internal/index"
)

// startedIn is what the started derivation reads: nothing, so it runs once, when the index starts.
type startedIn struct{}

// Module is the clock on the index: an I/O module that reads c, its one
// outside thing, and commits when the index started by it.
func Module(c Clock) *index.Module {
	return index.Declare("clock", "The time, read from the clock SE was handed.",
		index.IO(),
		index.Derived("started", time.Time{}, "When the index started, by this clock.",
			func(startedIn) (time.Time, error) { return c.Now(), nil }),
	)
}
