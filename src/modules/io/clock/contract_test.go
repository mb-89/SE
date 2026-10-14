package clock_test

import (
	"testing"
	"time"

	"github.com/mb-89/SE/src/modules/io/clock"
)

// step is the time the contract lets pass: long enough to measure on the
// wall clock, short enough to keep the real clock's suite fast.
const step = 5 * time.Millisecond

// contract is the one suite every Clock keeps, the fake as the real one.
// fresh answers a new clock for each case.
func contract(t *testing.T, fresh func() clock.Clock) {
	t.Run("now never goes back", func(t *testing.T) {
		c := fresh()
		last := c.Now()
		for range 100 {
			n := c.Now()
			if n.Before(last) {
				t.Fatalf("now went back from %v to %v", last, n)
			}
			last = n
		}
	})
	t.Run("sleep lets its time pass", func(t *testing.T) {
		c := fresh()
		start := c.Now()
		c.Sleep(step)
		if got := c.Now().Sub(start); got < step {
			t.Fatalf("slept %v, only %v passed", step, got)
		}
	})
	t.Run("sleep of nothing returns", func(t *testing.T) {
		c := fresh()
		start := c.Now()
		c.Sleep(0)
		c.Sleep(-time.Second)
		if c.Now().Before(start) {
			t.Fatal("now went back")
		}
	})
	t.Run("after waits for its time", func(t *testing.T) {
		c := fresh()
		select {
		case at := <-c.After(time.Hour):
			t.Fatalf("an hour's wait fired at once, at %v", at)
		default:
		}
	})
	t.Run("after fires once its time has passed", func(t *testing.T) {
		c := fresh()
		start := c.Now()
		ch := c.After(step)
		c.Sleep(step)
		if at := <-ch; at.Sub(start) < step {
			t.Fatalf("fired %v after it was asked, before its %v", at.Sub(start), step)
		}
	})
	t.Run("after of nothing fires at once", func(t *testing.T) {
		c := fresh()
		start := c.Now()
		if at := <-c.After(0); at.Before(start) {
			t.Fatalf("fired at %v, before it was asked at %v", at, start)
		}
	})
}
