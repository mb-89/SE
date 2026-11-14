package host

import (
	"fmt"
	"syscall"
)

// bootKey and bootValue are where Windows counts its boots.
const (
	bootKey   = `SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters`
	bootValue = "BootId"
)

func platformBoot() (string, error) {
	key, err := syscall.UTF16PtrFromString(bootKey)
	if err != nil {
		return "", err
	}
	var h syscall.Handle
	if err := syscall.RegOpenKeyEx(syscall.HKEY_LOCAL_MACHINE, key, 0, syscall.KEY_READ, &h); err != nil {
		return "", err
	}
	defer syscall.RegCloseKey(h)
	name, err := syscall.UTF16PtrFromString(bootValue)
	if err != nil {
		return "", err
	}
	var typ uint32
	buf := make([]byte, 8)
	n := uint32(len(buf))
	if err := syscall.RegQueryValueEx(h, name, nil, &typ, &buf[0], &n); err != nil {
		return "", err
	}
	if typ != syscall.REG_DWORD {
		return "", fmt.Errorf("%s is of registry type %d, and wants a REG_DWORD", bootValue, typ)
	}
	return bootFromCounter(buf[:n])
}
