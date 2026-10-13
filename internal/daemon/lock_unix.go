//go:build unix

package daemon

import (
	"os"
	"syscall"
)

// lock takes the daemon's lifetime lock, held by the OS until the process ends.
func lock(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, ErrRunning
	}
	return f, nil
}

func detached() *syscall.SysProcAttr { return &syscall.SysProcAttr{Setsid: true} }
