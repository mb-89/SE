package template

import (
	"os"
	"path/filepath"
	"testing"
)

// The tests read SE's checkout, two folders up, as the Python engine's ROOT: its scripts name SE's
// commands (rule dangling).
func TestMain(m *testing.M) {
	s.se = filepath.Join("..", "..")
	os.Exit(m.Run())
}
