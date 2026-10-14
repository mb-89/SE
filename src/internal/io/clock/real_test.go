package clock_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/io/clock"
)

func TestTheRealClockKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, clock.Real)
}
