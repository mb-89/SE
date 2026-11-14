package host

import "syscall"

func platformProc(pid int) (string, error) {
	h, err := syscall.OpenProcess(queryLimitedInformation, false, uint32(pid))
	if err != nil {
		return "", err
	}
	defer syscall.CloseHandle(h)
	var created, exited, kernel, user syscall.Filetime
	if err := syscall.GetProcessTimes(h, &created, &exited, &kernel, &user); err != nil {
		return "", err
	}
	return markFromFiletime(created.HighDateTime, created.LowDateTime)
}
