// Package disk is the I/O module for files and folders: the one place SE
// reads, writes, lists, locks or atomically replaces a file, such as the
// runtime folder, daemon.json, the logs and the daemon's lock. Code that
// needs the disk takes a Disk as an argument; the se binary hands it Real, a
// test hands it a Fake, so a case replays.
package disk

import (
	"errors"
	"io"
)

// ErrLocked says another holder has the lock Lock asked for.
var ErrLocked = errors.New("the lock is held")

// Disk is what SE asks of the filesystem. A path that names nothing fails
// with an error that is fs.ErrNotExist; a file is written with mode 0644 and
// a folder made with 0755.
type Disk interface {
	// ReadFile answers the whole of a file.
	ReadFile(path string) ([]byte, error)
	// WriteFile makes or truncates a file and writes data; its folder must exist.
	WriteFile(path string, data []byte) error
	// Replace puts data at path whole or not at all: a reader sees the old
	// file or the new one, never part of either. Its folder must exist.
	Replace(path string, data []byte) error
	// Create makes or truncates a file and answers it open for writing.
	Create(path string) (io.WriteCloser, error)
	// Append opens a file for writing at its end, making it where it is not.
	// What the real disk answers is an *os.File, which a process can be handed
	// as its output.
	Append(path string) (io.WriteCloser, error)
	// Exists says whether path is a file or a folder.
	Exists(path string) (bool, error)
	// List answers the names in a folder, sorted.
	List(dir string) ([]string, error)
	// Walk answers every file under root, by its path, sorted; folders are
	// walked into, not named.
	Walk(root string) ([]string, error)
	// MkdirAll makes a folder and every folder above it that is missing.
	MkdirAll(dir string) error
	// MkdirTemp makes a new folder in dir, or in the temporary folder where
	// dir is "", named pattern with a random part in place of its last *.
	MkdirTemp(dir, pattern string) (string, error)
	// Rename moves a file or a folder, replacing a file at to.
	Rename(from, to string) error
	// Remove removes a file or an empty folder.
	Remove(path string) error
	// RemoveAll removes path and all it holds; a path that names nothing is no error.
	RemoveAll(path string) error
	// Lock takes the lock file at path, making it where it is not, and
	// answers ErrLocked while another holder has it. Closing what it answers
	// lets the lock go; the real disk lets it go when the process ends, too.
	Lock(path string) (io.Closer, error)
}
