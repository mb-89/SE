//go:build unix

package disk

import (
	"io"
	"os"
	"syscall"
)

// lock takes an exclusive flock on the file, which the OS lets go when the process ends.
func lock(path string) (io.Closer, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, ErrLocked
	}
	return f, nil
}
