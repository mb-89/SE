//go:build windows

package disk

import (
	"errors"
	"io"
	"io/fs"
	"os"
	"syscall"
)

// lock on Windows opens the lock file with no sharing, so a second holder cannot open it.
func lock(path string) (io.Closer, error) {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	h, err := syscall.CreateFile(p, syscall.GENERIC_READ|syscall.GENERIC_WRITE, 0, nil,
		syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, &fs.PathError{Op: "lock", Path: path, Err: err}
	}
	if err != nil {
		return nil, ErrLocked
	}
	return os.NewFile(uintptr(h), path), nil
}
