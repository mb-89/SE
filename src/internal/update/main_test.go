package update_test

import (
	"os"
	"testing"

	"github.com/mb-89/SE/src/internal/gitenv"
)

// TestMain keeps the git these tests run in their own temp repositories.
func TestMain(m *testing.M) {
	// git's repository variables point it elsewhere under a pre-push hook.
	for _, v := range gitenv.Vars {
		_ = os.Unsetenv(v) // fails only on a name with "=" or NUL, which Vars hold none of
	}
	os.Exit(m.Run())
}
