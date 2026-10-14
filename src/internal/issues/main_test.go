package issues_test

import (
	"os"
	"testing"

	ioenv "github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
)

// TestMain keeps the git these tests run in their own temp repositories.
func TestMain(m *testing.M) {
	if err := git.Clear(ioenv.Real()); err != nil {
		panic(err)
	}
	os.Exit(m.Run())
}
