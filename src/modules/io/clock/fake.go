package clock

import (
	"sort"
	"sync"
	"time"
)

// Fake is a clock that moves only when told: by Advance, or by a Sleep, which
// passes its time at once. It never follows the wall clock, so a test that
// runs on it reads the same times on every run.
type Fake struct {
	mu      sync.Mutex
	now     time.Time
	waiters []waiter
}

type waiter struct {
	at time.Time
	ch chan time.Time
}

// NewFake answers a fake clock that stands at at.
func NewFake(at time.Time) *Fake { return &Fake{now: at} }

// Now answers the time the fake stands at.
func (f *Fake) Now() time.Time {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.now
}

// Advance moves the fake on by d and fires every After whose time has come,
// earliest first. A d <= 0 moves nothing.
func (f *Fake) Advance(d time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if d <= 0 {
		return
	}
	f.now = f.now.Add(d)
	kept := f.waiters[:0]
	var due []waiter
	for _, w := range f.waiters {
		if w.at.After(f.now) {
			kept = append(kept, w)
		} else {
			due = append(due, w)
		}
	}
	f.waiters = kept
	sort.SliceStable(due, func(i, j int) bool { return due[i].at.Before(due[j].at) })
	for _, w := range due {
		w.ch <- f.now
	}
}

// Sleep passes d on the fake at once: the sleeper is told time went by.
func (f *Fake) Sleep(d time.Duration) { f.Advance(d) }

// After answers a channel that receives the fake's time once it has been
// moved d on; d <= 0 receives at once.
func (f *Fake) After(d time.Duration) <-chan time.Time {
	f.mu.Lock()
	defer f.mu.Unlock()
	ch := make(chan time.Time, 1)
	if d <= 0 {
		ch <- f.now
		return ch
	}
	f.waiters = append(f.waiters, waiter{at: f.now.Add(d), ch: ch})
	return ch
}
