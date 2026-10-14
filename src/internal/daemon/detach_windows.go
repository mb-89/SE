//go:build windows

package daemon

import "syscall"

// detachedProcess is DETACHED_PROCESS: the daemon outlives the console that started it.
const detachedProcess = 0x00000008

func detached() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP | detachedProcess}
}
