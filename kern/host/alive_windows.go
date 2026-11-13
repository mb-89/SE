//go:build windows

package host

import "syscall"

const (
	queryLimitedInformation = 0x1000
	stillActive             = 259
)

// alive says whether a process runs at pid: it opens, and has not exited yet.
func alive(pid int) bool {
	if pid <= 0 {
		return false
	}
	h, err := syscall.OpenProcess(queryLimitedInformation, false, uint32(pid))
	if err != nil {
		return false
	}
	defer syscall.CloseHandle(h)
	var code uint32
	if err := syscall.GetExitCodeProcess(h, &code); err != nil {
		return false
	}
	return code == stillActive
}
