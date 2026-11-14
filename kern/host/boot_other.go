//go:build !linux && !darwin && !windows

package host

import "errors"

func platformBoot() (string, error) { return "", errors.New("this platform names no boot") }
