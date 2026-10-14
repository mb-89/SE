package env_test

import (
	"slices"
	"testing"

	"github.com/mb-89/SE/src/modules/io/env"
)

func TestTheFakeEnvironmentKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func() env.Env { return env.NewFake() })
}

func TestTheFakeEnvironmentHoldsWhatItWasMadeWith(t *testing.T) {
	t.Parallel()
	f := env.NewFake("B=2", "A=1=x")
	if got := f.Environ(); !slices.Equal(got, []string{"A=1=x", "B=2"}) {
		t.Fatalf("environ %q", got)
	}
	if f.Getenv("A") != "1=x" || f.Getenv("C") != "" {
		t.Fatalf("A %q, C %q", f.Getenv("A"), f.Getenv("C"))
	}
}
