//go:build windows

package host

import (
	"os"
	"os/exec"
	"strings"
	"syscall"
)

// noWindow starts the starter with no console window.
const noWindow = 0x08000000

// detached readies a command that a starter launches and leaves: the shell's
// `start /b` runs it and exits, so its parent has ended and a tree kill from
// the caller (a host ending a hook) walks past it. From quackitect v5's
// src/index/detach_windows.go.
func detached(run *exec.Cmd) *exec.Cmd {
	shell := os.Getenv("ComSpec")
	if shell == "" {
		shell = "cmd.exe"
	}
	words := []string{syscall.EscapeArg(run.Path)}
	for _, one := range run.Args[1:] {
		words = append(words, syscall.EscapeArg(one))
	}
	starter := exec.Command(shell)
	starter.Dir, starter.Env = run.Dir, run.Env
	starter.Stdin, starter.Stdout, starter.Stderr = run.Stdin, run.Stdout, run.Stderr
	starter.SysProcAttr = &syscall.SysProcAttr{
		CmdLine:       syscall.EscapeArg(shell) + ` /d /s /c "start "" /b ` + strings.Join(words, " ") + `"`,
		HideWindow:    true,
		CreationFlags: noWindow,
	}
	return starter
}
