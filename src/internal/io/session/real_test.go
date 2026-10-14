package session_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/io/session"
)

func TestTheLogFolderKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) session.Log { return session.Folder(t.TempDir()) })
}
