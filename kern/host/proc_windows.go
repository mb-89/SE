package host

import (
	"fmt"
	"syscall"
)

// platformProc answers the creation time of the process at pid while it runs:
// Windows keeps an ended process's object, its times among them, while any
// handle to it stays open, so an ended process (exit code other than
// STILL_ACTIVE) names no start, as alive says it runs nowhere.
func platformProc(pid int) (string, error) {
	h, err := syscall.OpenProcess(queryLimitedInformation, false, uint32(pid))
	if err != nil {
		return "", err
	}
	defer syscall.CloseHandle(h)
	var code uint32
	if err := syscall.GetExitCodeProcess(h, &code); err != nil {
		return "", err
	}
	if code != stillActive {
		return "", fmt.Errorf("pid %d ended with exit code %d", pid, code)
	}
	var created, exited, kernel, user syscall.Filetime
	if err := syscall.GetProcessTimes(h, &created, &exited, &kernel, &user); err != nil {
		return "", err
	}
	return markFromFiletime(created.HighDateTime, created.LowDateTime)
}
