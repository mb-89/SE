package host

import "golang.org/x/sys/unix"

func platformBoot() (string, error) {
	tv, err := unix.SysctlTimeval("kern.boottime")
	if err != nil {
		return "", err
	}
	return bootFromTimeval(int64(tv.Sec), int64(tv.Usec))
}
