package clock_test

import (
	"testing"
	"time"

	"github.com/mb-89/SE/src/index/indextest"
	"github.com/mb-89/SE/src/modules/io/clock"
)

func TestTheClockModuleCommitsWhenTheIndexStarted(t *testing.T) {
	t.Parallel()
	f, err := indextest.New(clock.Module(clock.NewFake(start)))
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Derive("started"); err != nil {
		t.Fatal(err)
	}
	if got, _ := f.Out("started"); !got.Provided || got.V.(time.Time) != start {
		t.Fatalf("started = %+v, want %v", got, start)
	}
}
