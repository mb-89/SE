//go:build !linux && !darwin && !windows

package host

import "errors"

func platformProc(int) (string, error) {
	return "", errors.New("this platform names no start of a process")
}
