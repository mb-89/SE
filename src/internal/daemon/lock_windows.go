//go:build windows

package daemon

import (
	"os"
	"syscall"
)

// lock on Windows opens the lock file with no sharing, so a second daemon cannot open it.
func lock(path string) (*os.File, error) {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	h, err := syscall.CreateFile(p, syscall.GENERIC_READ|syscall.GENERIC_WRITE, 0, nil,
		syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return nil, ErrRunning
	}
	return os.NewFile(uintptr(h), path), nil
}
