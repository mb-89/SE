//go:build !windows

package host

import (
	"errors"
	"syscall"
)

// alive says whether a process runs at pid: signal 0 reaches it, or reaches
// it and is refused, which a running process of another user answers.
func alive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}
