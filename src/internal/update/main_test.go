package update_test

import (
	"os"
	"testing"

	"github.com/mb-89/SE/src/internal/gitenv"
)

// TestMain keeps the git these tests run in their own temp repositories.
func TestMain(m *testing.M) {
	gitenv.Clear()
	os.Exit(m.Run())
}
