package env_test

import (
	"testing"

	"github.com/mb-89/SE/src/modules/io/env"
)

func TestTheRealEnvironmentKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, env.Real)
}
