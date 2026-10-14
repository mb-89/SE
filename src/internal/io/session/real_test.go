package session_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/session"
)

func TestTheLogFolderKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) session.Log { return session.Folder(disk.Real(), t.TempDir()) })
}

func TestTheLogFolderOnTheFakeDiskKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) session.Log {
		d := disk.NewFake()
		if err := d.MkdirAll("/logs"); err != nil {
			t.Fatal(err)
		}
		return session.Folder(d, "/logs")
	})
}
