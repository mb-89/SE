package gitenv_test

import (
	"os"
	"testing"

	"github.com/mb-89/SE/src/internal/gitenv"
)

func TestClear(t *testing.T) {
	for _, v := range gitenv.Vars {
		t.Setenv(v, "/elsewhere")
	}
	gitenv.Clear()
	for _, v := range gitenv.Vars {
		if got, ok := os.LookupEnv(v); ok {
			t.Errorf("%s = %q after Clear", v, got)
		}
	}
}
