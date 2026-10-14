package clock_test

import (
	"testing"
	"time"

	"github.com/mb-89/SE/src/modules/io/clock"
)

var start = time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)

func TestTheFakeClockKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func() clock.Clock { return clock.NewFake(start) })
}

func TestTheFakeClockMovesOnlyWhenTold(t *testing.T) {
	t.Parallel()
	f := clock.NewFake(start)
	for range 3 {
		if got := f.Now(); got != start {
			t.Fatalf("the fake moved by itself: %v", got)
		}
	}
	soon, later := f.After(time.Minute), f.After(time.Hour)
	f.Advance(59 * time.Second)
	select {
	case <-soon:
		t.Fatal("a minute's wait fired after 59 seconds")
	default:
	}
	f.Advance(time.Second)
	if at := <-soon; at != start.Add(time.Minute) {
		t.Fatalf("fired at %v", at)
	}
	select {
	case <-later:
		t.Fatal("an hour's wait fired after a minute")
	default:
	}
	f.Sleep(time.Hour)
	if at := <-later; at != start.Add(time.Hour+time.Minute) {
		t.Fatalf("fired at %v", at)
	}
	if f.Now() != start.Add(time.Hour+time.Minute) {
		t.Fatalf("now %v", f.Now())
	}
}
