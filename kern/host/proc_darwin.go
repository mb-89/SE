package host

import (
	"fmt"

	"golang.org/x/sys/unix"
)

func platformProc(pid int) (string, error) {
	kp, err := unix.SysctlKinfoProc("kern.proc.pid", pid)
	if err != nil {
		return "", err
	}
	if int(kp.Proc.P_pid) != pid {
		return "", fmt.Errorf("kern.proc.pid %d answers pid %d", pid, kp.Proc.P_pid)
	}
	st := kp.Proc.P_starttime
	return markFromStartTimeval(int64(st.Sec), int64(st.Usec))
}
