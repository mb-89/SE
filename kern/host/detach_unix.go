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

// let leaves the started core to run on its own while this process lives on
// as its parent: a goroutine waits for it, so a core that ends, as se stop
// asks, is reaped at once and no zombie of a long-lived starter (the MCP
// door) answers signal 0 to the stop's wait. A short-lived starter, a hook,
// exits before it and the core is reparented.
func let(run *exec.Cmd) error {
	go func() { _ = run.Wait() }()
	return nil
}
