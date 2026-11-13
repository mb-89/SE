//go:build !windows

package host

import (
	"os/exec"
	"syscall"
)

// detached readies a command to lead a session of its own, so the end of its
// starter's group, a hook's shell, leaves it running. From quackitect v5's
// src/index/detach_unix.go.
func detached(run *exec.Cmd) *exec.Cmd {
	if run.SysProcAttr == nil {
		run.SysProcAttr = &syscall.SysProcAttr{}
	}
	run.SysProcAttr.Setsid = true
	return run
}
